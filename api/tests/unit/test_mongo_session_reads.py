import asyncio
from copy import deepcopy
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, call

import pytest
from bson import ObjectId
from pymongo.errors import OperationFailure

from app.errors import ApplicationError, ErrorCode
from app.repositories.mongo_session_repository import MongoSessionRepository
from app.schemas.sessions import SessionDetailResponse
from app.services.mapping import SESSION_SUMMARY_FIELDS

SESSION_ID = "68df8b00aef4d8537282f001"
TIMESTAMP = datetime(2026, 10, 1, 9, 7, 4, tzinfo=timezone.utc)
DEFAULT_PROJECTION = {
    "_id": 1, "schema_version": 1, "started_at": 1, "received_at": 1,
    "status": 1, "completion_time": 1, "last_step_executed": 1, "execution_outcome": 1,
}


@pytest.fixture
def repository():
    # These mocks record driver calls and return prepared documents. They do not
    # emulate MongoDB's projection or sort behavior.
    cursor = MagicMock()
    cursor.__aenter__ = AsyncMock(return_value=cursor)
    cursor.__aexit__ = AsyncMock(return_value=False)
    cursor.sort.return_value = cursor
    cursor.to_list = AsyncMock(return_value=[])
    collection = MagicMock()
    collection.find.return_value = cursor  # find() is deliberately synchronous.
    collection.find_one = AsyncMock(return_value=None)
    database = MagicMock()
    database.__getitem__.return_value = collection
    return MongoSessionRepository(database), collection, cursor


@pytest.mark.parametrize(
    ("fields", "projection"),
    [
        (SESSION_SUMMARY_FIELDS, DEFAULT_PROJECTION),
        (("session_id",), {"_id": 1}),
        (("metadata.invoked_by.name", "metadata.boundary", "started_at", "session_id"), {
            "_id": 1, "metadata.invoked_by.name": 1, "metadata.boundary": 1, "started_at": 1,
        }),
        (("metadata", "execution_outcome.defect_count", "session_id"), {
            "_id": 1, "metadata": 1, "execution_outcome.defect_count": 1,
        }),
    ],
)
def test_list_uses_only_an_inclusion_projection_and_unbounded_sorted_cursor(repository, fields, projection):
    repo, collection, cursor = repository
    assert asyncio.run(repo.list_all(fields)) == []
    collection.find.assert_called_once_with({}, projection)
    cursor.sort.assert_called_once_with([("started_at", -1), ("_id", -1)])
    cursor.to_list.assert_awaited_once_with(length=None)
    cursor.__aexit__.assert_awaited_once()
    collection.find_one.assert_not_awaited()


def test_list_maps_ids_without_mutating_documents_or_serializing_datetimes(repository):
    repo, _, cursor = repository
    document = {
        "_id": ObjectId(SESSION_ID),
        "started_at": TIMESTAMP,
        "metadata": {"a.b": {"$set": "$status"}, "_id": "nested", "large": 9223372036854775807},
    }
    snapshot = deepcopy(document)
    cursor.to_list.return_value = [document]
    records = asyncio.run(repo.list_all(("session_id", "started_at", "metadata")))
    assert records == [{
        "session_id": SESSION_ID, "started_at": TIMESTAMP, "metadata": snapshot["metadata"],
    }]
    assert document == snapshot
    assert records[0]["started_at"] is TIMESTAMP


def test_selected_reads_do_not_mutate_default_or_full_detail_projection(repository):
    repo, collection, _ = repository

    async def exercise():
        await repo.list_all(("metadata.invoked_by.name", "session_id"))
        await repo.list_all(SESSION_SUMMARY_FIELDS)
        await repo.list_all(("session_id",))
        await repo.get(SESSION_ID)

    asyncio.run(exercise())
    assert collection.find.call_args_list == [
        call({}, {"_id": 1, "metadata.invoked_by.name": 1}),
        call({}, DEFAULT_PROJECTION),
        call({}, {"_id": 1}),
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


@pytest.mark.parametrize("failure_point", ["find", "sort", "to_list"])
def test_list_read_failures_are_sanitized(repository, failure_point):
    repo, collection, cursor = repository
    method = collection.find if failure_point == "find" else getattr(cursor, failure_point)
    method.side_effect = OperationFailure("sensitive database details")
    with pytest.raises(ApplicationError) as caught:
        asyncio.run(repo.list_all(("session_id", "metadata")))
    assert caught.value.code == ErrorCode.INTERNAL_ERROR
    assert "sensitive" not in str(caught.value)


def test_detail_still_maps_the_complete_record(repository):
    repo, collection, _ = repository
    document = {"_id": ObjectId(SESSION_ID), "started_at": TIMESTAMP, "metadata": {"all": "values"}}
    snapshot = deepcopy(document)
    collection.find_one.return_value = document
    assert asyncio.run(repo.get(SESSION_ID.upper())) == {
        "session_id": SESSION_ID, "started_at": TIMESTAMP, "metadata": {"all": "values"},
    }
    assert document == snapshot


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
