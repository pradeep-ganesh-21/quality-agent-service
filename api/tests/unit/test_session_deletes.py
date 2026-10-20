"""Soft-delete contracts for single and bulk session deletion."""

import asyncio
import json
from datetime import datetime, timezone

import pytest

import app.services.session_service as service_module
from app.errors import ApplicationError, ErrorCode
from app.repositories.protocols import SessionState
from app.services.session_service import SessionService
from conftest import (
    INTERNAL_ERROR,
    INVALID_BODY,
    INVALID_FIELD,
    INVALID_JSON,
    MISSING_FIELD,
    SESSION_DELETED,
    SESSION_ID,
    SESSION_NOT_FOUND,
    UNSUPPORTED_MEDIA_TYPE,
)

OTHER_ID = "68df8b00aef4d8537282f003"
THIRD_ID = "68df8b00aef4d8537282f004"
NOW = datetime(2026, 10, 2, 8, 0, 0, 123456, tzinfo=timezone.utc)
STAMPED_AT = datetime(2026, 10, 2, 8, 0, 0, 123000, tzinfo=timezone.utc)
EARLIER = datetime(2026, 10, 1, 12, 0, 0, tzinfo=timezone.utc)
JSON_HEADERS = {"Content-Type": "application/json"}
BULK_PATH = "/v1/sessions/bulk-delete"


class FakeSessions:
    """Holds each session's deletion timestamp; it does not model MongoDB."""

    def __init__(self, sessions):
        self.deleted_at = dict(sessions)
        self.calls = []
        self.fail_on = None

    async def soft_delete(self, session_id, deleted_at):
        self.calls.append(("soft_delete", session_id, deleted_at))
        if session_id == self.fail_on:
            raise ApplicationError(ErrorCode.INTERNAL_ERROR)
        if session_id in self.deleted_at and self.deleted_at[session_id] is None:
            self.deleted_at[session_id] = deleted_at
            return True
        return False

    async def state(self, session_id):
        self.calls.append(("state", session_id))
        if session_id not in self.deleted_at:
            return None
        return SessionState(deleted_at=self.deleted_at[session_id])


class FakeRuns:
    def __init__(self, runs):
        # Maps a run name to [parent session ID, deletion timestamp].
        self.runs = {name: list(value) for name, value in runs.items()}
        self.calls = []
        self.failures = 0

    async def soft_delete_for_session(self, session_id, deleted_at):
        self.calls.append((session_id, deleted_at))
        if self.failures:
            self.failures -= 1
            raise ApplicationError(ErrorCode.INTERNAL_ERROR)
        matched = 0
        for run in self.runs.values():
            if run[0] == session_id and run[1] is None:
                run[1] = deleted_at
                matched += 1
        return matched

    def stamps(self):
        return {name: run[1] for name, run in self.runs.items()}


class FrozenClock(datetime):
    @classmethod
    def now(cls, tz=None):
        return NOW.astimezone(tz) if tz is not None else NOW


@pytest.fixture
def deletes(monkeypatch):
    monkeypatch.setattr(service_module, "datetime", FrozenClock)
    sessions = FakeSessions({SESSION_ID: None, OTHER_ID: EARLIER})
    runs = FakeRuns({
        "first": [SESSION_ID, None],
        "second": [SESSION_ID, None],
        "late": [OTHER_ID, None],
        "stamped": [OTHER_ID, EARLIER],
    })
    return SessionService(sessions, runs), sessions, runs


def expect_error(code, call):
    with pytest.raises(ApplicationError) as caught:
        asyncio.run(call())
    assert caught.value.code == code


def test_delete_stamps_the_session_then_its_runs_with_one_millisecond_timestamp(deletes):
    service, sessions, runs = deletes
    assert asyncio.run(service.delete_session(SESSION_ID)) is None
    assert sessions.deleted_at[SESSION_ID] == STAMPED_AT
    assert sessions.calls == [("soft_delete", SESSION_ID, STAMPED_AT)]
    assert runs.calls == [(SESSION_ID, STAMPED_AT)]
    assert runs.stamps() == {
        "first": STAMPED_AT, "second": STAMPED_AT, "late": None, "stamped": EARLIER,
    }


def test_delete_of_an_unknown_session_reports_not_found_without_touching_runs(deletes):
    service, sessions, runs = deletes
    expect_error(ErrorCode.SESSION_NOT_FOUND, lambda: service.delete_session(THIRD_ID))
    assert sessions.calls == [("soft_delete", THIRD_ID, STAMPED_AT), ("state", THIRD_ID)]
    assert runs.calls == []


def test_repeated_delete_keeps_the_original_timestamp_and_stamps_only_late_runs(deletes):
    service, sessions, runs = deletes
    expect_error(ErrorCode.SESSION_DELETED, lambda: service.delete_session(OTHER_ID))
    assert sessions.deleted_at[OTHER_ID] == EARLIER
    assert runs.calls == [(OTHER_ID, EARLIER)]
    assert runs.stamps()["late"] == EARLIER
    assert runs.stamps()["stamped"] == EARLIER


def test_a_run_stamp_failure_leaves_the_session_deleted_and_a_repeat_repairs_the_runs(deletes):
    service, sessions, runs = deletes
    runs.failures = 1
    expect_error(ErrorCode.INTERNAL_ERROR, lambda: service.delete_session(SESSION_ID))
    assert sessions.deleted_at[SESSION_ID] == STAMPED_AT
    assert runs.stamps()["first"] is None

    expect_error(ErrorCode.SESSION_DELETED, lambda: service.delete_session(SESSION_ID))
    assert runs.stamps()["first"] == runs.stamps()["second"] == STAMPED_AT


def test_an_unmatched_guard_on_a_live_session_is_an_internal_error(deletes):
    service, sessions, runs = deletes

    async def never_matches(session_id, deleted_at):
        return False

    sessions.soft_delete = never_matches
    expect_error(ErrorCode.INTERNAL_ERROR, lambda: service.delete_session(SESSION_ID))
    assert runs.calls == []


def test_bulk_delete_deduplicates_and_reports_each_identifier_once_in_order(deletes):
    service, sessions, runs = deletes
    ids = [THIRD_ID, SESSION_ID, OTHER_ID, SESSION_ID, "not-an-id", THIRD_ID]
    result = asyncio.run(service.delete_sessions({"session_ids": ids}))
    assert result.deleted == [SESSION_ID]
    assert result.already_deleted == [OTHER_ID]
    assert result.not_found == [THIRD_ID, "not-an-id"]
    assert [call[1] for call in sessions.calls if call[0] == "soft_delete"] == [
        THIRD_ID, SESSION_ID, OTHER_ID, "not-an-id",
    ]
    assert runs.calls == [(SESSION_ID, STAMPED_AT), (OTHER_ID, EARLIER)]


def test_bulk_delete_is_not_atomic_and_a_repeat_reports_processed_identifiers(deletes):
    service, sessions, _ = deletes
    sessions.deleted_at[THIRD_ID] = None
    sessions.fail_on = THIRD_ID
    body = {"session_ids": [SESSION_ID, THIRD_ID]}
    expect_error(ErrorCode.INTERNAL_ERROR, lambda: service.delete_sessions(body))
    assert sessions.deleted_at[SESSION_ID] == STAMPED_AT

    sessions.fail_on = None
    result = asyncio.run(service.delete_sessions(body))
    assert (result.deleted, result.already_deleted, result.not_found) == (
        [THIRD_ID], [SESSION_ID], []
    )


@pytest.mark.parametrize(
    ("body", "code"),
    [
        ({}, ErrorCode.MISSING_FIELD),
        ({"session_ids": None}, ErrorCode.INVALID_FIELD),
        ({"session_ids": []}, ErrorCode.INVALID_FIELD),
        ({"session_ids": SESSION_ID}, ErrorCode.INVALID_FIELD),
        ({"session_ids": {"id": SESSION_ID}}, ErrorCode.INVALID_FIELD),
        ({"session_ids": [SESSION_ID, 1]}, ErrorCode.INVALID_FIELD),
        ({"session_ids": [None]}, ErrorCode.INVALID_FIELD),
        ({"session_ids": [[SESSION_ID]]}, ErrorCode.INVALID_FIELD),
        ({"session_ids": [SESSION_ID], "reason": "cleanup"}, ErrorCode.INVALID_FIELD),
        ({"session_ids": [SESSION_ID], "_id": SESSION_ID}, ErrorCode.INVALID_FIELD),
        ({"session_ids": [SESSION_ID], "extra": 2**64}, ErrorCode.VALUE_OUT_OF_RANGE),
        ({"session_ids": ["\ud800"]}, ErrorCode.INVALID_FIELD),
        ({"session_ids": [SESSION_ID], "a\x00": 1}, ErrorCode.INVALID_KEY),
    ],
)
def test_bulk_delete_rejects_invalid_bodies_before_any_repository_call(deletes, body, code):
    service, sessions, runs = deletes
    expect_error(code, lambda: service.delete_sessions(body))
    assert sessions.calls == runs.calls == []


def test_delete_route_returns_no_content(api_client):
    client, sessions, runs = api_client
    sessions.soft_delete.return_value = True
    response = client.delete(f"/v1/sessions/{SESSION_ID}")
    assert response.status_code == 204
    assert response.content == b""
    sessions.soft_delete.assert_awaited_once()
    assert sessions.soft_delete.await_args.args[0] == SESSION_ID
    runs.soft_delete_for_session.assert_awaited_once()


@pytest.mark.parametrize(
    ("state", "status", "body"),
    [
        (None, 404, SESSION_NOT_FOUND),
        (SessionState(deleted_at=EARLIER), 409, SESSION_DELETED),
    ],
)
def test_delete_route_maps_missing_and_already_deleted_sessions(api_client, state, status, body):
    client, sessions, _ = api_client
    sessions.state.return_value = state
    response = client.delete(f"/v1/sessions/{SESSION_ID}")
    assert response.status_code == status
    assert response.json() == body


def test_delete_route_treats_a_malformed_identifier_as_not_found(api_client):
    client, sessions, runs = api_client
    response = client.delete("/v1/sessions/not-an-id")
    assert response.status_code == 404
    assert response.json() == SESSION_NOT_FOUND
    assert runs.soft_delete_for_session.await_count == 0


def test_delete_route_failures_are_sanitized(api_client):
    client, sessions, _ = api_client
    sessions.soft_delete.side_effect = ApplicationError(ErrorCode.INTERNAL_ERROR)
    response = client.delete(f"/v1/sessions/{SESSION_ID}")
    assert response.status_code == 500
    assert response.json() == INTERNAL_ERROR


def test_bulk_delete_route_returns_all_three_lists(api_client):
    client, sessions, _ = api_client

    async def soft_delete(session_id, deleted_at):
        return session_id == SESSION_ID

    async def state(session_id):
        return SessionState(deleted_at=EARLIER) if session_id == OTHER_ID else None

    sessions.soft_delete.side_effect = soft_delete
    sessions.state.side_effect = state
    response = client.post(
        BULK_PATH,
        content=json.dumps({"session_ids": [SESSION_ID, OTHER_ID, THIRD_ID, SESSION_ID]}),
        headers=JSON_HEADERS,
    )
    assert response.status_code == 200
    assert response.json() == {
        "deleted": [SESSION_ID], "already_deleted": [OTHER_ID], "not_found": [THIRD_ID],
    }


def test_bulk_delete_route_keeps_empty_lists(api_client):
    client, _, _ = api_client
    response = client.post(
        BULK_PATH, content=json.dumps({"session_ids": [SESSION_ID]}), headers=JSON_HEADERS
    )
    assert response.status_code == 200
    assert response.json() == {"deleted": [], "already_deleted": [], "not_found": [SESSION_ID]}


@pytest.mark.parametrize(
    ("content", "headers", "status", "body"),
    [
        (b'{"session_ids": []}', JSON_HEADERS, 400, INVALID_FIELD),
        (b"{}", JSON_HEADERS, 400, MISSING_FIELD),
        (b"{", JSON_HEADERS, 400, INVALID_JSON),
        (b'["68df8b00aef4d8537282f001"]', JSON_HEADERS, 400, INVALID_BODY),
        (b'{"session_ids": ["68df8b00aef4d8537282f001"]}', {"Content-Type": "text/plain"},
         415, UNSUPPORTED_MEDIA_TYPE),
    ],
)
def test_bulk_delete_route_rejects_invalid_requests_without_persistence(
    api_client, content, headers, status, body
):
    client, sessions, runs = api_client
    response = client.post(BULK_PATH, content=content, headers=headers)
    assert response.status_code == status
    assert response.json() == body
    assert sessions.mock_calls == runs.mock_calls == []


def test_bulk_delete_path_is_not_a_session_identifier_for_reads(api_client):
    client, sessions, _ = api_client
    response = client.get(BULK_PATH)
    assert response.status_code == 404
    assert response.json() == SESSION_NOT_FOUND
    sessions.soft_delete.assert_not_awaited()


def test_patch_on_a_soft_deleted_session_reports_deletion(api_client):
    client, sessions, _ = api_client
    sessions.patch_open_session.side_effect = ApplicationError(ErrorCode.SESSION_DELETED)
    response = client.patch(f"/v1/sessions/{SESSION_ID}", content=b"{}", headers=JSON_HEADERS)
    assert response.status_code == 409
    assert response.json() == SESSION_DELETED
