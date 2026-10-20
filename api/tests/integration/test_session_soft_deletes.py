"""Pin soft-delete behavior against a real MongoDB server.

These checks depend on server semantics that mocks cannot reproduce: null
equality matching a missing field, guarded update match counts, and multi-document
run stamping.
"""

from datetime import datetime, timedelta, timezone

import pytest
from bson import ObjectId

from app.errors import ApplicationError, ErrorCode
from app.repositories.indexes import ensure_indexes
from app.repositories.mongo_run_repository import MongoRunRepository
from app.repositories.mongo_session_repository import MongoSessionRepository
from app.services.session_service import SessionService

pytestmark = pytest.mark.integration

START = datetime(2026, 10, 1, 9, 0, 0, tzinfo=timezone.utc)
EARLIER = datetime(2026, 9, 30, 9, 0, 0, tzinfo=timezone.utc)


def session_document(started_at, **extra):
    return {
        "schema_version": 1,
        "started_at": started_at,
        "received_at": started_at,
        "status": "IN_PROGRESS",
        "completion_time": None,
        "last_step_executed": [],
        "execution_outcome": None,
        "metadata": {},
        **extra,
    }


def run_document(session_id, **extra):
    return {
        "session_id": ObjectId(session_id),
        "schema_version": 1,
        "step": "pair-actions",
        "command": "actions-pairer",
        "verdict": "PASS",
        "occurred_at": START,
        "received_at": START,
        **extra,
    }


async def setup(database):
    await ensure_indexes(database)
    sessions = MongoSessionRepository(database)
    runs = MongoRunRepository(database)
    return SessionService(sessions, runs), sessions


async def run_stamps(database, session_id):
    cursor = database["runs"].find({"session_id": ObjectId(session_id)}, {"deleted_at": 1})
    return [document.get("deleted_at") for document in await cursor.to_list(length=None)]


def test_lists_exclude_stamped_sessions_and_treat_null_and_missing_as_live(run_against_database):
    async def main(database):
        service, sessions = await setup(database)
        missing = await sessions.create(session_document(START))
        explicit = await sessions.create(session_document(START - timedelta(minutes=1), deleted_at=None))
        stamped = await sessions.create(
            session_document(START - timedelta(minutes=2), deleted_at=EARLIER)
        )
        unfiltered = await service.list_sessions([("fields", "session_id")])
        filtered = await service.list_sessions([("status", "IN_PROGRESS"), ("page_size", "1")])
        following = await service.list_sessions(
            [("status", "IN_PROGRESS"), ("page_size", "1"), ("cursor", filtered.next_cursor)]
        )
        return missing, explicit, stamped, unfiltered, filtered, following

    missing, explicit, stamped, unfiltered, filtered, following = run_against_database(main)
    assert [item["session_id"] for item in unfiltered.items] == [missing, explicit]
    assert unfiltered.total_count == 2
    assert filtered.total_count == 2
    assert [item["session_id"] for item in following.items] == [explicit]
    assert following.next_cursor is None
    assert stamped not in [item["session_id"] for item in unfiltered.items]


def test_soft_delete_guard_matches_once_and_never_overwrites_or_removes(run_against_database):
    async def main(database):
        _, sessions = await setup(database)
        session_id = await sessions.create(session_document(START))
        first = await sessions.soft_delete(session_id, EARLIER)
        second = await sessions.soft_delete(session_id, START)
        stored = await database["sessions"].find_one({"_id": ObjectId(session_id)})
        count = await database["sessions"].count_documents({})
        return first, second, stored, count

    first, second, stored, count = run_against_database(main)
    assert (first, second) == (True, False)
    assert stored["deleted_at"] == EARLIER
    assert count == 1


def test_delete_stamps_runs_and_a_repeat_stamps_late_runs_with_the_original_time(
    run_against_database,
):
    async def main(database):
        service, sessions = await setup(database)
        session_id = await sessions.create(session_document(START))
        other_id = await sessions.create(session_document(START - timedelta(minutes=1)))
        await database["runs"].insert_many([
            run_document(session_id),
            run_document(session_id, deleted_at=None),
            run_document(other_id),
        ])
        await service.delete_session(session_id)
        state = await sessions.state(session_id)
        after_delete = await run_stamps(database, session_id)
        # A run inserted after the delete, as in the accepted creation race.
        await database["runs"].insert_one(run_document(session_id))
        with pytest.raises(ApplicationError) as repeat:
            await service.delete_session(session_id)
        after_repeat = await run_stamps(database, session_id)
        untouched = await run_stamps(database, other_id)
        detail = await service.get_session(session_id)
        return state, after_delete, repeat.value.code, after_repeat, untouched, detail

    state, after_delete, repeat_code, after_repeat, untouched, detail = run_against_database(main)
    assert state.deleted_at is not None
    assert after_delete == [state.deleted_at, state.deleted_at]
    assert repeat_code == ErrorCode.SESSION_DELETED
    assert after_repeat == [state.deleted_at] * 3
    assert untouched == [None]
    assert detail["deleted_at"] == state.deleted_at
    assert [run["deleted_at"] for run in detail["runs"]] == [state.deleted_at] * 3


def test_repeated_bulk_request_reports_processed_identifiers_as_already_deleted(
    run_against_database,
):
    async def main(database):
        service, sessions = await setup(database)
        first = await sessions.create(session_document(START))
        second = await sessions.create(session_document(START - timedelta(minutes=1)))
        unknown = str(ObjectId())
        body = {"session_ids": [first, second, first, unknown]}
        initial = await service.delete_sessions(body)
        repeated = await service.delete_sessions(body)
        return first, second, unknown, initial, repeated

    first, second, unknown, initial, repeated = run_against_database(main)
    assert (initial.deleted, initial.already_deleted, initial.not_found) == (
        [first, second], [], [unknown]
    )
    assert (repeated.deleted, repeated.already_deleted, repeated.not_found) == (
        [], [first, second], [unknown]
    )


def test_patch_rejects_a_soft_deleted_session_and_accepts_one_without_the_field(
    run_against_database,
):
    async def main(database):
        service, sessions = await setup(database)
        deleted = await sessions.create(session_document(START))
        legacy = await sessions.create(session_document(START - timedelta(minutes=1)))
        await sessions.soft_delete(deleted, EARLIER)
        with pytest.raises(ApplicationError) as rejected:
            await service.patch_session(deleted, {"status": "COMPLETED"})
        patched = await service.patch_session(legacy, {"status": "COMPLETED"})
        stored = await database["sessions"].find_one({"_id": ObjectId(deleted)})
        return rejected.value.code, patched, legacy, stored

    code, patched, legacy, stored = run_against_database(main)
    assert code == ErrorCode.SESSION_DELETED
    assert patched == legacy
    assert stored["status"] == "IN_PROGRESS"
