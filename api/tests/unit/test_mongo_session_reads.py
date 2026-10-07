import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, call

import pytest
from bson import ObjectId
from pymongo.errors import OperationFailure

from app.errors import ApplicationError, ErrorCode
from app.repositories.mongo_session_repository import MongoSessionRepository
from app.repositories.protocols import (
    PagePosition,
    SessionFilters,
    SessionListQuery,
)
from app.schemas.sessions import SessionDetailResponse
from app.services.mapping import SESSION_SUMMARY_FIELDS

SESSION_ID = "68df8b00aef4d8537282f001"
OTHER_ID = "68df8b00aef4d8537282f099"
TIMESTAMP = datetime(2026, 10, 1, 9, 7, 4, tzinfo=timezone.utc)
LATER = TIMESTAMP + timedelta(hours=1)
DEFAULT_PROJECTION = {
    "_id": 1, "schema_version": 1, "started_at": 1, "received_at": 1,
    "status": 1, "completion_time": 1, "last_step_executed": 1, "execution_outcome": 1,
}
DESCENDING = [("started_at", -1), ("_id", -1)]
ASCENDING = [("started_at", 1), ("_id", 1)]


def query(**overrides) -> SessionListQuery:
    settings = {"fields": SESSION_SUMMARY_FIELDS, "page_size": 25}
    return SessionListQuery(**{**settings, **overrides})


def document(session_id=SESSION_ID, started_at=TIMESTAMP, **extra) -> dict:
    return {"_id": ObjectId(session_id), "started_at": started_at, **extra}


@pytest.fixture
def repository():
    # These mocks record driver calls and return prepared documents. They do not
    # emulate MongoDB's projection, filter, or sort behavior.
    cursor = MagicMock()
    cursor.__aenter__ = AsyncMock(return_value=cursor)
    cursor.__aexit__ = AsyncMock(return_value=False)
    cursor.sort.return_value = cursor
    cursor.to_list = AsyncMock(return_value=[])
    collection = MagicMock()
    collection.find.return_value = cursor  # find() is deliberately synchronous.
    collection.find_one = AsyncMock(return_value=None)
    collection.count_documents = AsyncMock(return_value=0)
    database = MagicMock()
    database.__getitem__.return_value = collection
    return MongoSessionRepository(database), collection, cursor


@pytest.mark.parametrize(
    ("fields", "projection"),
    [
        (SESSION_SUMMARY_FIELDS, DEFAULT_PROJECTION),
        (("session_id",), {"_id": 1, "started_at": 1}),
        (("metadata.invoked_by.name", "metadata.boundary", "started_at", "session_id"), {
            "_id": 1, "started_at": 1, "metadata.invoked_by.name": 1, "metadata.boundary": 1,
        }),
        (("metadata", "execution_outcome.defect_count", "session_id"), {
            "_id": 1, "started_at": 1, "metadata": 1, "execution_outcome.defect_count": 1,
        }),
    ],
)
def test_first_page_reads_one_extra_record_in_newest_first_order(repository, fields, projection):
    repo, collection, cursor = repository
    page = asyncio.run(repo.list_page(query(fields=fields)))
    assert (page.items, page.total_count) == ([], 0)
    collection.count_documents.assert_awaited_once_with({})
    collection.find.assert_called_once_with({}, projection)
    cursor.sort.assert_called_once_with(DESCENDING)
    cursor.to_list.assert_awaited_once_with(length=26)
    cursor.__aexit__.assert_awaited_once()
    # An empty page is terminal in both directions and needs no extra probe.
    collection.find_one.assert_not_awaited()


def test_sort_key_is_always_projected_but_never_returned_unselected(repository):
    repo, collection, cursor = repository
    cursor.to_list.return_value = [document(metadata={"boundary": "checkout"})]
    page = asyncio.run(repo.list_page(query(fields=("session_id", "metadata"))))
    assert collection.find.call_args.args[1] == {"_id": 1, "started_at": 1, "metadata": 1}
    assert page.items == [{"metadata": {"boundary": "checkout"}, "session_id": SESSION_ID}]
    assert page.newest.started_at == TIMESTAMP
    assert page.oldest.session_id == SESSION_ID


def test_selected_sort_key_is_retained_in_records(repository):
    repo, _, cursor = repository
    cursor.to_list.return_value = [document()]
    page = asyncio.run(repo.list_page(query(fields=("session_id", "started_at"))))
    assert page.items == [{"started_at": TIMESTAMP, "session_id": SESSION_ID}]


def test_page_is_trimmed_and_reports_more_older_records(repository):
    repo, collection, cursor = repository
    collection.count_documents.return_value = 7
    cursor.to_list.return_value = [
        document(f"{index:024x}", TIMESTAMP + timedelta(minutes=index)) for index in range(3, 0, -1)
    ]
    page = asyncio.run(repo.list_page(query(fields=("session_id",), page_size=2)))
    assert [record["session_id"] for record in page.items] == [f"{3:024x}", f"{2:024x}"]
    assert (page.total_count, page.has_older, page.has_newer) == (7, True, False)
    assert page.newest.session_id == f"{3:024x}"
    assert page.oldest.session_id == f"{2:024x}"
    collection.find_one.assert_not_awaited()


def test_full_first_page_without_extra_record_has_no_next_page(repository):
    repo, collection, cursor = repository
    cursor.to_list.return_value = [document(), document(OTHER_ID)]
    page = asyncio.run(repo.list_page(query(fields=("session_id",), page_size=2)))
    assert (page.has_older, page.has_newer) == (False, False)
    collection.find_one.assert_not_awaited()


def test_forward_cursor_excludes_the_boundary_and_probes_for_newer_records(repository):
    repo, collection, cursor = repository
    cursor.to_list.return_value = [document(OTHER_ID)]
    position = PagePosition(started_at=LATER, session_id=SESSION_ID, direction="next")
    page = asyncio.run(repo.list_page(query(fields=("session_id",), position=position)))

    expected_spec = {"$or": [
        {"started_at": {"$lt": LATER}},
        {"started_at": LATER, "_id": {"$lt": ObjectId(SESSION_ID)}},
    ]}
    collection.find.assert_called_once_with(expected_spec, {"_id": 1, "started_at": 1})
    cursor.sort.assert_called_once_with(DESCENDING)
    # The anchored record may have changed, so reachability is queried, not assumed.
    collection.find_one.assert_awaited_once_with(
        {"$or": [
            {"started_at": {"$gt": TIMESTAMP}},
            {"started_at": TIMESTAMP, "_id": {"$gt": ObjectId(OTHER_ID)}},
        ]},
        {"_id": 1},
    )
    assert (page.has_newer, page.has_older) == (False, False)
    assert collection.count_documents.await_args_list == [call({})]


def test_backward_cursor_reads_ascending_and_restores_newest_first_order(repository):
    repo, collection, cursor = repository
    collection.find_one.return_value = {"_id": ObjectId(SESSION_ID)}
    cursor.to_list.return_value = [
        document(f"{index:024x}", TIMESTAMP + timedelta(minutes=index)) for index in (1, 2, 3)
    ]
    position = PagePosition(started_at=TIMESTAMP, session_id=SESSION_ID, direction="previous")
    page = asyncio.run(repo.list_page(query(fields=("session_id",), page_size=2, position=position)))

    collection.find.assert_called_once_with(
        {"$or": [
            {"started_at": {"$gt": TIMESTAMP}},
            {"started_at": TIMESTAMP, "_id": {"$gt": ObjectId(SESSION_ID)}},
        ]},
        {"_id": 1, "started_at": 1},
    )
    cursor.sort.assert_called_once_with(ASCENDING)
    # Reading ascending returns the two nearest newer records, newest last.
    assert [record["session_id"] for record in page.items] == [f"{2:024x}", f"{1:024x}"]
    assert (page.has_newer, page.has_older) == (True, True)
    assert page.newest.session_id == f"{2:024x}"
    assert page.oldest.session_id == f"{1:024x}"
    collection.find_one.assert_awaited_once_with(
        {"$or": [
            {"started_at": {"$lt": TIMESTAMP + timedelta(minutes=1)}},
            {"started_at": TIMESTAMP + timedelta(minutes=1), "_id": {"$lt": ObjectId(f"{1:024x}")}},
        ]},
        {"_id": 1},
    )


def test_stale_cursor_returns_an_empty_terminal_page_with_the_live_total(repository):
    repo, collection, _ = repository
    collection.count_documents.return_value = 12
    position = PagePosition(started_at=TIMESTAMP, session_id=SESSION_ID, direction="next")
    page = asyncio.run(repo.list_page(query(fields=("session_id",), position=position)))
    assert (page.items, page.total_count) == ([], 12)
    assert (page.has_newer, page.has_older, page.newest, page.oldest) == (False, False, None, None)
    collection.find_one.assert_not_awaited()


@pytest.mark.parametrize(
    ("filters", "expected"),
    [
        (SessionFilters(status="COMPLETED"), {"status": "COMPLETED"}),
        (SessionFilters(started_from=TIMESTAMP), {"started_at": {"$gte": TIMESTAMP}}),
        (SessionFilters(started_before=LATER), {"started_at": {"$lt": LATER}}),
        (
            SessionFilters(started_from=TIMESTAMP, started_before=LATER),
            {"started_at": {"$gte": TIMESTAMP, "$lt": LATER}},
        ),
        (
            SessionFilters(boundary_contains="pay.ments"),
            {"metadata.boundary": {
                "$regex": "pay\\.ments", "$options": "i", "$not": {"$type": "array"},
            }},
        ),
        (
            SessionFilters(invoked_by_email="$ops@example.invalid"),
            {
                "metadata.invoked_by": {"$not": {"$type": "array"}},
                "metadata.invoked_by.email": {
                    "$eq": "$ops@example.invalid", "$not": {"$type": "array"},
                },
            },
        ),
    ],
)
def test_each_filter_builds_its_documented_predicate(repository, filters, expected):
    repo, collection, _ = repository
    asyncio.run(repo.list_page(query(fields=("session_id",), filters=filters)))
    collection.find.assert_called_once_with(expected, {"_id": 1, "started_at": 1})
    collection.count_documents.assert_awaited_once_with(expected)


def test_filters_combine_conjunctively(repository):
    repo, collection, _ = repository
    filters = SessionFilters(
        status="FAILED",
        started_from=TIMESTAMP,
        started_before=LATER,
        boundary_contains="checkout",
        invoked_by_email="ops@example.invalid",
    )
    asyncio.run(repo.list_page(query(fields=("session_id",), filters=filters)))
    assert collection.find.call_args.args[0] == {
        "status": "FAILED",
        "started_at": {"$gte": TIMESTAMP, "$lt": LATER},
        "metadata.boundary": {
            "$regex": "checkout", "$options": "i", "$not": {"$type": "array"},
        },
        "metadata.invoked_by": {"$not": {"$type": "array"}},
        "metadata.invoked_by.email": {
            "$eq": "ops@example.invalid", "$not": {"$type": "array"},
        },
    }


def test_filters_and_boundary_are_conjoined_without_overwriting_the_range(repository):
    repo, collection, cursor = repository
    cursor.to_list.return_value = [document()]
    filters = SessionFilters(status="COMPLETED", started_from=TIMESTAMP, started_before=LATER)
    position = PagePosition(started_at=LATER, session_id=OTHER_ID, direction="next")
    asyncio.run(repo.list_page(query(fields=("session_id",), filters=filters, position=position)))

    filter_spec = {"status": "COMPLETED", "started_at": {"$gte": TIMESTAMP, "$lt": LATER}}
    assert collection.find.call_args.args[0] == {"$and": [
        filter_spec,
        {"$or": [
            {"started_at": {"$lt": LATER}},
            {"started_at": LATER, "_id": {"$lt": ObjectId(OTHER_ID)}},
        ]},
    ]}
    # The total covers every filter match and ignores the page boundary.
    collection.count_documents.assert_awaited_once_with(filter_spec)
    assert collection.find_one.await_args.args[0]["$and"][0] == filter_spec


def test_list_maps_ids_without_mutating_documents_or_serializing_datetimes(repository):
    repo, _, cursor = repository
    stored = document(metadata={
        "a.b": {"$set": "$status"}, "_id": "nested", "large": 9223372036854775807,
    })
    snapshot = deepcopy(stored)
    cursor.to_list.return_value = [stored]
    page = asyncio.run(repo.list_page(query(fields=("session_id", "started_at", "metadata"))))
    assert page.items == [{
        "started_at": TIMESTAMP, "metadata": snapshot["metadata"], "session_id": SESSION_ID,
    }]
    assert stored == snapshot
    assert page.items[0]["started_at"] is TIMESTAMP


def test_a_record_without_the_sort_key_is_not_paginated(repository):
    repo, _, cursor = repository
    cursor.to_list.return_value = [{"_id": ObjectId(SESSION_ID)}]
    with pytest.raises(ApplicationError) as caught:
        asyncio.run(repo.list_page(query(fields=("session_id",))))
    assert caught.value.code == ErrorCode.INTERNAL_ERROR


def test_selected_reads_do_not_mutate_default_or_full_detail_projection(repository):
    repo, collection, _ = repository

    async def exercise():
        await repo.list_page(query(fields=("metadata.invoked_by.name", "session_id")))
        await repo.list_page(query())
        await repo.list_page(query(fields=("session_id",)))
        await repo.get(SESSION_ID)

    asyncio.run(exercise())
    assert collection.find.call_args_list == [
        call({}, {"_id": 1, "started_at": 1, "metadata.invoked_by.name": 1}),
        call({}, DEFAULT_PROJECTION),
        call({}, {"_id": 1, "started_at": 1}),
    ]
    collection.find_one.assert_awaited_once_with(
        {"_id": ObjectId(SESSION_ID)}, {**DEFAULT_PROJECTION, "metadata": 1},
    )


def test_full_detail_projection_matches_the_full_response_model(repository):
    repo, collection, _ = repository
    asyncio.run(repo.get(SESSION_ID))
    projection = collection.find_one.call_args.args[1]
    expected_fields = (set(SessionDetailResponse.model_fields) - {"session_id", "runs"}) | {"_id"}
    assert projection == {field: 1 for field in expected_fields}


@pytest.mark.parametrize("failure_point", ["count_documents", "find", "sort", "to_list"])
def test_list_read_failures_are_sanitized(repository, failure_point):
    repo, collection, cursor = repository
    method = (
        getattr(collection, failure_point)
        if failure_point in ("count_documents", "find")
        else getattr(cursor, failure_point)
    )
    method.side_effect = OperationFailure("sensitive database details")
    with pytest.raises(ApplicationError) as caught:
        asyncio.run(repo.list_page(query(fields=("session_id", "metadata"))))
    assert caught.value.code == ErrorCode.INTERNAL_ERROR
    assert "sensitive" not in str(caught.value)


def test_reachability_probe_failures_are_sanitized(repository):
    repo, collection, cursor = repository
    cursor.to_list.return_value = [document()]
    collection.find_one.side_effect = OperationFailure("sensitive database details")
    position = PagePosition(started_at=LATER, session_id=OTHER_ID, direction="next")
    with pytest.raises(ApplicationError) as caught:
        asyncio.run(repo.list_page(query(fields=("session_id",), position=position)))
    assert caught.value.code == ErrorCode.INTERNAL_ERROR
    assert "sensitive" not in str(caught.value)


def test_a_malformed_cursor_identifier_issues_no_mongodb_operation(repository):
    repo, collection, _ = repository
    position = PagePosition(started_at=TIMESTAMP, session_id="not-an-id", direction="next")
    with pytest.raises(ApplicationError) as caught:
        asyncio.run(repo.list_page(query(fields=("session_id",), position=position)))
    assert caught.value.code == ErrorCode.INVALID_FIELD
    collection.find.assert_not_called()
    collection.find_one.assert_not_awaited()


def test_detail_still_maps_the_complete_record(repository):
    repo, collection, _ = repository
    stored = {"_id": ObjectId(SESSION_ID), "started_at": TIMESTAMP, "metadata": {"all": "values"}}
    snapshot = deepcopy(stored)
    collection.find_one.return_value = stored
    assert asyncio.run(repo.get(SESSION_ID.upper())) == {
        "session_id": SESSION_ID, "started_at": TIMESTAMP, "metadata": {"all": "values"},
    }
    assert stored == snapshot


@pytest.mark.parametrize(
    "session_id",
    [
        "not-an-id", "", "68df8b00aef4d8537282f0", SESSION_ID + "00",
        # ObjectId(None) would generate a new identifier instead of failing.
        None,
        1, 1.5, True, [], {},
        # ObjectId accepts these, but the repository contract is a string identifier.
        ObjectId(SESSION_ID), bytes.fromhex(SESSION_ID),
    ],
)
def test_invalid_detail_identifiers_do_not_query_mongodb(repository, session_id):
    repo, collection, _ = repository
    assert asyncio.run(repo.get(session_id)) is None
    collection.find_one.assert_not_awaited()
    collection.find.assert_not_called()
