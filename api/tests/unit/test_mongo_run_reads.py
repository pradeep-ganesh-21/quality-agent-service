"""Verify the MongoDB commands the run read adapter issues.

These mocks record driver calls and return prepared documents. They do not
emulate MongoDB's projection or sort behavior.
"""

import asyncio
from copy import deepcopy
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from bson import ObjectId
from pymongo.errors import OperationFailure

from app.errors import ApplicationError, ErrorCode
from app.repositories.mongo_run_repository import MongoRunRepository

SESSION_ID = "68df8b00aef4d8537282f001"
RUN_ID = "68df8b00aef4d8537282f002"
OCCURRED_AT = datetime(2026, 10, 1, 9, 17, 58, tzinfo=timezone.utc)
RECEIVED_AT = datetime(2026, 10, 1, 9, 17, 59, 456000, tzinfo=timezone.utc)
RUN_PROJECTION = {
    "_id": 1, "session_id": 1, "schema_version": 1, "step": 1, "command": 1,
    "verdict": 1, "occurred_at": 1, "received_at": 1, "details": 1, "deleted_at": 1,
}
DELETED_AT = datetime(2026, 10, 2, 8, 0, 0, 123000, tzinfo=timezone.utc)


@pytest.fixture
def repository():
    cursor = MagicMock()
    cursor.__aenter__ = AsyncMock(return_value=cursor)
    cursor.__aexit__ = AsyncMock(return_value=False)
    cursor.sort.return_value = cursor
    cursor.to_list = AsyncMock(return_value=[])
    collection = MagicMock()
    collection.find.return_value = cursor  # find() is deliberately synchronous.
    collection.update_many = AsyncMock(return_value=MagicMock(matched_count=2, modified_count=2))
    database = MagicMock()
    database.__getitem__.return_value = collection
    return MongoRunRepository(database), collection, cursor, database


def expect_error(code, call):
    with pytest.raises(ApplicationError) as caught:
        call()
    assert caught.value.code == code
    return caught.value


def test_reads_use_the_runs_collection(repository):
    _, _, _, database = repository
    database.__getitem__.assert_called_once_with("runs")


def test_list_filters_by_parent_id_and_uses_an_unbounded_sorted_cursor(repository):
    repo, collection, cursor, _ = repository
    assert asyncio.run(repo.list_for_session(SESSION_ID)) == []
    collection.find.assert_called_once_with({"session_id": ObjectId(SESSION_ID)}, RUN_PROJECTION)
    cursor.sort.assert_called_once_with([("occurred_at", 1), ("_id", 1)])
    cursor.to_list.assert_awaited_once_with(length=None)
    cursor.__aexit__.assert_awaited_once()


def test_list_maps_both_identifiers_without_mutating_documents(repository):
    repo, _, cursor, _ = repository
    document = {
        "_id": ObjectId(RUN_ID),
        "session_id": ObjectId(SESSION_ID),
        "schema_version": 1,
        "step": "pair-actions",
        "command": "actions-pairer",
        "verdict": "PASS",
        "occurred_at": OCCURRED_AT,
        "received_at": RECEIVED_AT,
        "details": {"a.b": {"$set": "$verdict"}, "_id": "nested", "large": 2**63 - 1},
        "deleted_at": None,
    }
    snapshot = deepcopy(document)
    cursor.to_list.return_value = [document]
    records = asyncio.run(repo.list_for_session(SESSION_ID))
    assert records == [{
        "run_id": RUN_ID,
        "session_id": SESSION_ID,
        "schema_version": 1,
        "step": "pair-actions",
        "command": "actions-pairer",
        "verdict": "PASS",
        "occurred_at": OCCURRED_AT,
        "received_at": RECEIVED_AT,
        "details": snapshot["details"],
        "deleted_at": None,
    }]
    assert document == snapshot
    assert records[0]["occurred_at"] is OCCURRED_AT
    assert "_id" not in records[0]


def test_list_maps_a_missing_deletion_timestamp_to_null_and_keeps_a_stored_one(repository):
    repo, _, cursor, _ = repository
    cursor.to_list.return_value = [
        {"_id": ObjectId(RUN_ID), "session_id": ObjectId(SESSION_ID)},
        {"_id": ObjectId(SESSION_ID), "session_id": ObjectId(SESSION_ID), "deleted_at": DELETED_AT},
    ]
    records = asyncio.run(repo.list_for_session(SESSION_ID))
    assert [record["deleted_at"] for record in records] == [None, DELETED_AT]


def test_soft_delete_stamps_only_unstamped_runs_of_the_parent(repository):
    repo, collection, _, _ = repository
    assert asyncio.run(repo.soft_delete_for_session(SESSION_ID.upper(), DELETED_AT)) == 2
    collection.update_many.assert_awaited_once_with(
        {"session_id": ObjectId(SESSION_ID), "deleted_at": None},
        {"$set": {"deleted_at": DELETED_AT}},
        upsert=False,
    )
    # Soft delete never removes a document.
    assert collection.delete_one.mock_calls == []
    assert collection.delete_many.mock_calls == []


@pytest.mark.parametrize(
    "session_id",
    ["", "not-an-object-id", SESSION_ID + "00", None, 1, ObjectId(SESSION_ID), bytes.fromhex(SESSION_ID)],
)
def test_soft_delete_with_a_malformed_identifier_stamps_nothing(repository, session_id):
    repo, collection, _, _ = repository
    assert asyncio.run(repo.soft_delete_for_session(session_id, DELETED_AT)) == 0
    collection.update_many.assert_not_awaited()


def test_soft_delete_failures_are_sanitized(repository):
    repo, collection, _, _ = repository
    collection.update_many.side_effect = OperationFailure("sensitive database details")
    error = expect_error(
        ErrorCode.INTERNAL_ERROR,
        lambda: asyncio.run(repo.soft_delete_for_session(SESSION_ID, DELETED_AT)),
    )
    assert error.__cause__ is None and error.__suppress_context__


def test_list_preserves_order_and_maps_every_document(repository):
    repo, _, cursor, _ = repository
    cursor.to_list.return_value = [
        {"_id": ObjectId(RUN_ID), "session_id": ObjectId(SESSION_ID), "step": "first"},
        {"_id": ObjectId(SESSION_ID), "session_id": ObjectId(SESSION_ID), "step": "second"},
    ]
    records = asyncio.run(repo.list_for_session(SESSION_ID))
    assert [record["step"] for record in records] == ["first", "second"]
    assert [record["run_id"] for record in records] == [RUN_ID, SESSION_ID]


@pytest.mark.parametrize(
    "session_id",
    [
        "", "not-an-object-id", "68df8b00aef4d8537282f0", SESSION_ID + "00",
        SESSION_ID + " ", "68df8b00aef4d8537282f00g",
    ],
)
def test_malformed_identifier_strings_report_not_found_without_querying(repository, session_id):
    repo, collection, _, _ = repository
    expect_error(
        ErrorCode.SESSION_NOT_FOUND,
        lambda: asyncio.run(repo.list_for_session(session_id)),
    )
    collection.find.assert_not_called()


@pytest.mark.parametrize(
    "session_id",
    [
        # ObjectId(None) would generate a new identifier instead of failing, which
        # would silently list runs for an unrelated parent.
        None,
        1, 1.5, True, [], {},
        # ObjectId accepts these, but the repository contract is a string identifier.
        ObjectId(SESSION_ID), bytes.fromhex(SESSION_ID),
    ],
)
def test_non_string_identifiers_report_not_found_without_querying(repository, session_id):
    repo, collection, _, _ = repository
    expect_error(
        ErrorCode.SESSION_NOT_FOUND,
        lambda: asyncio.run(repo.list_for_session(session_id)),
    )
    collection.find.assert_not_called()


def test_uppercase_parent_identifiers_are_normalized_in_the_filter(repository):
    repo, collection, _, _ = repository
    asyncio.run(repo.list_for_session(SESSION_ID.upper()))
    assert collection.find.call_args.args[0] == {"session_id": ObjectId(SESSION_ID)}


@pytest.mark.parametrize("failure_point", ["find", "sort", "to_list"])
def test_run_read_failures_are_sanitized(repository, failure_point):
    repo, collection, cursor, _ = repository
    method = collection.find if failure_point == "find" else getattr(cursor, failure_point)
    method.side_effect = OperationFailure("sensitive database details")
    error = expect_error(
        ErrorCode.INTERNAL_ERROR, lambda: asyncio.run(repo.list_for_session(SESSION_ID))
    )
    assert error.__cause__ is None and error.__suppress_context__
