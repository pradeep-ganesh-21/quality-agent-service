"""Verify the MongoDB commands the session write adapter issues.

These mocks record driver calls and return prepared results. They do not emulate
MongoDB's merge, guard, or document-size behavior; that belongs to integration tests.
"""

import asyncio
from copy import deepcopy
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from bson import ObjectId
from bson.errors import InvalidDocument
from pymongo.errors import ConnectionFailure, DocumentTooLarge, OperationFailure, WriteError

from app.errors import ApplicationError, ErrorCode
from app.repositories.mongo_session_repository import MongoSessionRepository

SESSION_ID = "68df8b00aef4d8537282f001"
STARTED_AT = datetime(2026, 10, 1, 9, 7, 4, 123000, tzinfo=timezone.utc)
RECEIVED_AT = datetime(2026, 10, 1, 9, 7, 5, 456000, tzinfo=timezone.utc)
DOCUMENT = {
    "schema_version": 1,
    "started_at": STARTED_AT,
    "received_at": RECEIVED_AT,
    "status": "IN_PROGRESS",
    "completion_time": None,
    "last_step_executed": [],
    "execution_outcome": None,
    "metadata": {"a.b": {"$set": "$status", "_id": "nested"}, "large": 2**63 - 1},
}


@pytest.fixture
def repository():
    collection = MagicMock()
    collection.insert_one = AsyncMock(return_value=MagicMock(inserted_id=ObjectId(SESSION_ID)))
    collection.update_one = AsyncMock(
        return_value=MagicMock(matched_count=1, modified_count=1)
    )
    collection.find_one = AsyncMock(return_value=None)
    database = MagicMock()
    database.__getitem__.return_value = collection
    return MongoSessionRepository(database), collection, database


def expect_error(code, call):
    with pytest.raises(ApplicationError) as caught:
        call()
    assert caught.value.code == code
    return caught.value


def test_writes_use_the_sessions_collection_without_overriding_write_concern(repository):
    _, _, database = repository
    database.__getitem__.assert_called_once_with("sessions")
    # Overriding the write concern here would discard the configured durability.
    assert database.get_collection.mock_calls == []
    assert database.with_options.mock_calls == []


def test_create_inserts_one_document_and_returns_the_generated_identifier(repository):
    repo, collection, _ = repository
    assert asyncio.run(repo.create(DOCUMENT)) == SESSION_ID
    collection.insert_one.assert_awaited_once()
    assert collection.insert_one.await_args.args[0] == DOCUMENT
    assert collection.update_one.await_count == 0
    assert collection.find_one.await_count == 0


def test_create_copies_the_document_so_driver_mutation_cannot_reach_the_caller(repository):
    repo, collection, _ = repository
    snapshot = deepcopy(DOCUMENT)
    asyncio.run(repo.create(DOCUMENT))
    inserted = collection.insert_one.await_args.args[0]
    assert inserted is not DOCUMENT
    inserted["_id"] = ObjectId(SESSION_ID)
    inserted["metadata"]["a.b"]["$set"] = "mutated"
    inserted["last_step_executed"].append("mutated")
    assert DOCUMENT == snapshot


def test_create_preserves_datetimes_and_large_integers_without_serializing(repository):
    repo, collection, _ = repository
    asyncio.run(repo.create(DOCUMENT))
    inserted = collection.insert_one.await_args.args[0]
    assert inserted["started_at"] == STARTED_AT and inserted["started_at"].tzinfo == timezone.utc
    assert isinstance(inserted["received_at"], datetime)
    assert inserted["metadata"]["large"] == 2**63 - 1
    assert type(inserted["schema_version"]) is int


@pytest.mark.parametrize(
    ("failure", "code"),
    [
        (DocumentTooLarge("document too large"), ErrorCode.DOCUMENT_TOO_LARGE),
        (InvalidDocument("cannot encode object"), ErrorCode.INVALID_FIELD),
        (UnicodeEncodeError("utf-8", "x", 0, 1, "surrogates not allowed"), ErrorCode.INVALID_FIELD),
        (OverflowError("MongoDB can only handle up to 8-byte ints"), ErrorCode.INVALID_FIELD),
        (OperationFailure("oversize", code=10334), ErrorCode.DOCUMENT_TOO_LARGE),
        (OperationFailure("oversize", code=17419), ErrorCode.DOCUMENT_TOO_LARGE),
        (OperationFailure("write failed", code=121), ErrorCode.INTERNAL_ERROR),
        (WriteError("write failed", code=11000), ErrorCode.INTERNAL_ERROR),
        (ConnectionFailure("sensitive connection details"), ErrorCode.INTERNAL_ERROR),
    ],
)
def test_insert_failures_map_to_sanitized_application_errors(repository, failure, code):
    repo, collection, _ = repository
    collection.insert_one.side_effect = failure
    error = expect_error(code, lambda: asyncio.run(repo.create(DOCUMENT)))
    assert error.__cause__ is None and error.__suppress_context__


def test_oversize_documents_are_not_reported_as_their_invalid_document_base_class():
    assert issubclass(DocumentTooLarge, InvalidDocument)


def test_patch_issues_one_guarded_pipeline_update_without_upsert(repository):
    repo, collection, _ = repository
    known = {
        "status": "COMPLETED",
        "completion_time": RECEIVED_AT,
        "last_step_executed": ["pair-actions"],
        "execution_outcome": {"defect_count": 2, "unknown": {"$set": "$status"}},
    }
    extras = {"invoked_by": {"name": "Operator"}, "a.b": {"$set": "$status"}}
    assert asyncio.run(repo.patch_open_session(SESSION_ID, known, extras)) == SESSION_ID

    collection.update_one.assert_awaited_once()
    filter_spec, pipeline = collection.update_one.await_args.args
    assert filter_spec == {"_id": ObjectId(SESSION_ID), "status": "IN_PROGRESS"}
    assert collection.update_one.await_args.kwargs == {"upsert": False}
    assert len(pipeline) == 1
    set_spec = pipeline[0]["$set"]
    assert set(set_spec) == set(known) | {"metadata"}
    for field, value in known.items():
        assert set_spec[field] == {"$literal": value}
    assert set_spec["metadata"] == {
        "$mergeObjects": [
            {"$ifNull": ["$metadata", {"$literal": {}}]},
            {"$literal": extras},
        ]
    }
    collection.find_one.assert_not_awaited()


def test_patch_always_assigns_metadata_even_without_extras(repository):
    repo, collection, _ = repository
    asyncio.run(repo.patch_open_session(SESSION_ID, {}, {}))
    set_spec = collection.update_one.await_args.args[1][0]["$set"]
    assert set_spec == {
        "metadata": {
            "$mergeObjects": [
                {"$ifNull": ["$metadata", {"$literal": {}}]},
                {"$literal": {}},
            ]
        }
    }


def test_patch_copies_values_so_driver_mutation_cannot_reach_the_caller(repository):
    repo, collection, _ = repository
    known = {"last_step_executed": ["pair-actions"], "execution_outcome": {"nested": {"a": 1}}}
    extras = {"invoked_by": {"name": "Operator"}}
    snapshots = deepcopy(known), deepcopy(extras)
    asyncio.run(repo.patch_open_session(SESSION_ID, known, extras))

    set_spec = collection.update_one.await_args.args[1][0]["$set"]
    set_spec["last_step_executed"]["$literal"].append("mutated")
    set_spec["execution_outcome"]["$literal"]["nested"]["a"] = 99
    set_spec["metadata"]["$mergeObjects"][1]["$literal"]["invoked_by"]["name"] = "mutated"
    assert (known, extras) == snapshots


def test_identical_update_succeeds_through_matched_count(repository):
    repo, collection, _ = repository
    collection.update_one.return_value = MagicMock(matched_count=1, modified_count=0)
    assert asyncio.run(repo.patch_open_session(SESSION_ID, {}, {})) == SESSION_ID
    collection.find_one.assert_not_awaited()


def test_unmatched_update_uses_one_id_only_lookup_to_report_a_missing_session(repository):
    repo, collection, _ = repository
    collection.update_one.return_value = MagicMock(matched_count=0, modified_count=0)
    expect_error(
        ErrorCode.SESSION_NOT_FOUND,
        lambda: asyncio.run(repo.patch_open_session(SESSION_ID, {"status": "FAILED"}, {})),
    )
    collection.find_one.assert_awaited_once_with({"_id": ObjectId(SESSION_ID)}, {"_id": 1})
    collection.update_one.assert_awaited_once()


def test_unmatched_update_on_an_existing_session_reports_a_terminal_conflict(repository):
    repo, collection, _ = repository
    collection.update_one.return_value = MagicMock(matched_count=0, modified_count=0)
    collection.find_one.return_value = {"_id": ObjectId(SESSION_ID)}
    expect_error(
        ErrorCode.SESSION_NOT_OPEN,
        lambda: asyncio.run(repo.patch_open_session(SESSION_ID, {}, {})),
    )
    collection.find_one.assert_awaited_once()


@pytest.mark.parametrize(
    "session_id",
    [
        "", "not-an-object-id", "68df8b00aef4d8537282f0", SESSION_ID + "00",
        SESSION_ID + " ", " " + SESSION_ID, "68df8b00aef4d8537282f00g",
    ],
)
def test_malformed_identifier_strings_report_not_found_without_touching_mongodb(
    repository, session_id
):
    repo, collection, _ = repository
    expect_error(
        ErrorCode.SESSION_NOT_FOUND,
        lambda: asyncio.run(repo.patch_open_session(session_id, {}, {})),
    )
    collection.update_one.assert_not_awaited()
    collection.find_one.assert_not_awaited()


@pytest.mark.parametrize(
    "session_id",
    [
        # ObjectId(None) would generate a new identifier instead of failing, which
        # would silently target an unrelated document.
        None,
        1, 1.5, True, [], {}, (), set(),
        # ObjectId accepts these, but the repository contract is a string identifier.
        ObjectId(SESSION_ID),
        bytes.fromhex(SESSION_ID),
        bytearray.fromhex(SESSION_ID),
    ],
)
def test_non_string_identifiers_report_not_found_without_touching_mongodb(
    repository, session_id
):
    repo, collection, _ = repository
    expect_error(
        ErrorCode.SESSION_NOT_FOUND,
        lambda: asyncio.run(repo.patch_open_session(session_id, {}, {})),
    )
    collection.update_one.assert_not_awaited()
    collection.find_one.assert_not_awaited()


@pytest.mark.parametrize("session_id", [SESSION_ID, SESSION_ID.upper()])
def test_valid_identifier_strings_are_normalized_in_the_filter_and_response(
    repository, session_id
):
    repo, collection, _ = repository
    assert asyncio.run(repo.patch_open_session(session_id, {}, {})) == SESSION_ID
    assert collection.update_one.await_args.args[0]["_id"] == ObjectId(SESSION_ID)


@pytest.mark.parametrize(
    ("failure", "code"),
    [
        (DocumentTooLarge("update too large"), ErrorCode.DOCUMENT_TOO_LARGE),
        (InvalidDocument("cannot encode object"), ErrorCode.INVALID_FIELD),
        (OperationFailure("oversize", code=10334), ErrorCode.DOCUMENT_TOO_LARGE),
        (OperationFailure("oversize", code=17419), ErrorCode.DOCUMENT_TOO_LARGE),
        (OperationFailure("update failed", code=121), ErrorCode.INTERNAL_ERROR),
        (WriteError("update failed", code=66), ErrorCode.INTERNAL_ERROR),
        (ConnectionFailure("sensitive connection details"), ErrorCode.INTERNAL_ERROR),
    ],
)
def test_update_failures_map_to_sanitized_application_errors(repository, failure, code):
    repo, collection, _ = repository
    collection.update_one.side_effect = failure
    error = expect_error(
        code, lambda: asyncio.run(repo.patch_open_session(SESSION_ID, {"status": "FAILED"}, {}))
    )
    assert error.__cause__ is None and error.__suppress_context__


def test_failures_during_the_disambiguating_lookup_are_also_sanitized(repository):
    repo, collection, _ = repository
    collection.update_one.return_value = MagicMock(matched_count=0, modified_count=0)
    collection.find_one.side_effect = ConnectionFailure("sensitive connection details")
    error = expect_error(
        ErrorCode.INTERNAL_ERROR, lambda: asyncio.run(repo.patch_open_session(SESSION_ID, {}, {}))
    )
    assert error.__cause__ is None and error.__suppress_context__
