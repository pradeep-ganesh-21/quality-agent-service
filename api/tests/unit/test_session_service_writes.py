"""Service-level partitioning, server-owned values, and repository delegation."""

import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest

from app.errors import ApplicationError, ErrorCode
from app.services import session_service as service_module
from app.services.mapping import (
    SESSION_CREATE_RESERVED_FIELDS,
    SESSION_PATCH_CONSUMED_FIELDS,
    SESSION_PATCH_RESERVED_FIELDS,
)
from app.services.session_service import SessionService
from conftest import RECEIVED_AT, SESSION_ID

STORED_RECEIVED_AT = RECEIVED_AT.replace(microsecond=456000)
STARTED_AT_INPUT = "2026-10-01T11:07:04.123999+02:00"
STORED_STARTED_AT = datetime(2026, 10, 1, 9, 7, 4, 123000, tzinfo=timezone.utc)
ARBITRARY_EXTRAS = {
    "boundary": "checkout",
    "recorded_by": {"name": "Agent", "email": "agent@example.invalid"},
    "invoked_by": {"name": "Operator"},
    "run_id": "legacy-value",
    "metadata": {"nested": "client supplied"},
    "a.b": {"$set": "$status", "_id": "nested", "__proto__": {"name": "data"}},
    "array": [None, True, 1, 1.5, "text", {}, []],
    "limits": {"min": -(2**63), "max": 2**63 - 1},
    "at": "2026-10-01T09:17:58Z",
    "occurred_at": "2026-10-01T09:17:58Z",
    "日本語": "値",
}
SESSION_ROOT_FIELDS = frozenset({
    "schema_version", "started_at", "received_at", "status",
    "completion_time", "last_step_executed", "execution_outcome", "metadata",
})


class RecordingSessionRepository:
    """Keeps the objects it receives so aliasing defects stay visible."""

    def __init__(self, session_id=SESSION_ID, failure=None):
        self.session_id = session_id
        self.failure = failure
        self.created = []
        self.patched = []

    async def create(self, values):
        self.created.append(values)
        if self.failure is not None:
            raise self.failure
        return self.session_id

    async def patch_open_session(self, session_id, known, extras):
        self.patched.append((session_id, known, extras))
        if self.failure is not None:
            raise self.failure
        return self.session_id

    async def get(self, session_id):
        raise AssertionError("Writes must not read a session.")

    async def list_all(self, fields):
        raise AssertionError("Writes must not list sessions.")


class UnusedRunRepository:
    async def list_for_session(self, session_id):
        raise AssertionError("Session writes must not query runs.")


class FrozenClock(datetime):
    calls: list = []

    @classmethod
    def now(cls, tz=None):
        cls.calls.append(tz)
        return RECEIVED_AT.astimezone(tz) if tz is not None else RECEIVED_AT


@pytest.fixture
def writes(monkeypatch):
    FrozenClock.calls = []
    monkeypatch.setattr(service_module, "datetime", FrozenClock)
    sessions = RecordingSessionRepository()
    return SessionService(sessions, UnusedRunRepository()), sessions


def create(service, body):
    return asyncio.run(service.create_session(body))


def patch(service, body, session_id=SESSION_ID):
    return asyncio.run(service.patch_session(session_id, body))


def expect_error(code, call, *args):
    with pytest.raises(ApplicationError) as caught:
        call(*args)
    assert caught.value.code == code


def test_minimal_create_builds_the_exact_stored_envelope(writes):
    service, sessions = writes
    assert create(service, {"started_at": STARTED_AT_INPUT}) == SESSION_ID
    document, = sessions.created
    assert document == {
        "schema_version": 1,
        "started_at": STORED_STARTED_AT,
        "received_at": STORED_RECEIVED_AT,
        "status": "IN_PROGRESS",
        "completion_time": None,
        "last_step_executed": [],
        "execution_outcome": None,
        "metadata": {},
    }
    assert type(document["schema_version"]) is int
    assert isinstance(document["started_at"], datetime)
    assert document["received_at"].tzinfo == timezone.utc
    assert FrozenClock.calls == [timezone.utc]


def test_create_never_generates_identifiers_or_a_duplicate_session_id(writes):
    service, sessions = writes
    create(service, {"started_at": STARTED_AT_INPUT})
    document, = sessions.created
    assert "_id" not in document and "session_id" not in document
    assert "runs" not in document and "metadata" in document


def test_create_moves_every_unrecognized_field_under_metadata_unchanged(writes):
    service, sessions = writes
    body = {"started_at": STARTED_AT_INPUT, **deepcopy(ARBITRARY_EXTRAS)}
    create(service, body)
    document, = sessions.created
    assert document["metadata"] == ARBITRARY_EXTRAS
    assert set(document) == SESSION_ROOT_FIELDS
    assert "started_at" not in document["metadata"]
    assert document["metadata"]["metadata"] == {"nested": "client supplied"}
    assert document["metadata"]["run_id"] == "legacy-value"
    assert document["metadata"]["at"] == document["metadata"]["occurred_at"] == "2026-10-01T09:17:58Z"
    assert type(document["metadata"]["array"][2]) is int
    assert type(document["metadata"]["array"][3]) is float


def test_create_does_not_alias_or_mutate_caller_owned_values(writes):
    service, sessions = writes
    body = {"started_at": STARTED_AT_INPUT, "recorded_by": {"name": "Agent"}, "list": [{"a": 1}]}
    snapshot = deepcopy(body)
    create(service, body)
    document, = sessions.created
    document["metadata"]["recorded_by"]["name"] = "Mutated by the driver"
    document["metadata"]["list"][0]["a"] = 99
    document["last_step_executed"].append("mutated")
    assert body == snapshot

    create(service, {"started_at": STARTED_AT_INPUT})
    first, second = sessions.created[0], sessions.created[-1]
    assert first["last_step_executed"] is not second["last_step_executed"]


def test_create_validates_deep_payloads_without_exhausting_the_stack(writes):
    service, sessions = writes
    deep: object = "leaf"
    for _ in range(5000):
        deep = {"k": deep}
    expect_error(
        ErrorCode.PAYLOAD_TOO_DEEP, create, service, {"started_at": STARTED_AT_INPUT, "deep": deep}
    )
    assert sessions.created == []


@pytest.mark.parametrize("field", sorted(SESSION_CREATE_RESERVED_FIELDS))
@pytest.mark.parametrize("value", [None, "value", {}, 1])
def test_create_rejects_each_reserved_field_before_model_validation(writes, field, value):
    service, sessions = writes
    expect_error(ErrorCode.FORBIDDEN_FIELD, create, service, {field: value})
    expect_error(
        ErrorCode.FORBIDDEN_FIELD, create, service, {"started_at": STARTED_AT_INPUT, field: value}
    )
    assert sessions.created == []
    assert FrozenClock.calls == []


def test_create_reserved_field_list_matches_the_documented_names():
    assert SESSION_CREATE_RESERVED_FIELDS == frozenset({
        "_id", "session_id", "received_at", "schema_version",
        "status", "completion_time", "last_step_executed", "execution_outcome",
    })
    assert SESSION_PATCH_RESERVED_FIELDS == frozenset({
        "_id", "session_id", "received_at", "schema_version", "started_at",
    })
    assert SESSION_PATCH_CONSUMED_FIELDS == frozenset({
        "status", "completion_time", "last_step_executed", "execution_outcome",
    })


def test_create_requires_a_started_at_and_distinguishes_missing_from_invalid(writes):
    service, sessions = writes
    expect_error(ErrorCode.MISSING_FIELD, create, service, {})
    expect_error(ErrorCode.MISSING_FIELD, create, service, {"boundary": "checkout"})
    expect_error(ErrorCode.INVALID_FIELD, create, service, {"started_at": None})
    assert sessions.created == []


@pytest.mark.parametrize(
    "value",
    ["2026-10-01T09:07:04", "2026-10-01", 1790000000, True, [], {}, "", "not a timestamp"],
)
def test_create_rejects_timestamps_without_an_explicit_offset(writes, value):
    service, sessions = writes
    expect_error(ErrorCode.INVALID_FIELD, create, service, {"started_at": value})
    assert sessions.created == []


def test_create_rejects_invalid_raw_values_before_reserved_fields(writes):
    service, sessions = writes
    expect_error(
        ErrorCode.VALUE_OUT_OF_RANGE, create, service,
        {"started_at": STARTED_AT_INPUT, "status": "COMPLETED", "huge": 2**63},
    )
    expect_error(
        ErrorCode.INVALID_KEY, create, service, {"started_at": STARTED_AT_INPUT, "a\x00b": 1},
    )
    assert sessions.created == []


def test_create_rejects_final_envelope_depth_over_one_hundred(writes):
    service, sessions = writes
    accepted = {"k": 0}
    for _ in range(97):
        accepted = {"k": accepted}
    create(service, {"started_at": STARTED_AT_INPUT, "extra": accepted})
    assert sessions.created[-1]["metadata"]["extra"] == accepted

    expect_error(
        ErrorCode.PAYLOAD_TOO_DEEP, create, service,
        {"started_at": STARTED_AT_INPUT, "extra": {"k": accepted}},
    )
    assert len(sessions.created) == 1


def test_create_propagates_repository_failures_without_retrying():
    sessions = RecordingSessionRepository(failure=ApplicationError(ErrorCode.DOCUMENT_TOO_LARGE))
    service = SessionService(sessions, UnusedRunRepository())
    expect_error(ErrorCode.DOCUMENT_TOO_LARGE, create, service, {"started_at": STARTED_AT_INPUT})
    assert len(sessions.created) == 1


def test_empty_patch_still_executes_one_guarded_update(writes):
    service, sessions = writes
    assert patch(service, {}) == SESSION_ID
    assert sessions.patched == [(SESSION_ID, {}, {})]
    assert FrozenClock.calls == []


def test_patch_passes_the_supplied_identifier_unchanged(writes):
    service, sessions = writes
    for session_id in (SESSION_ID, SESSION_ID.upper(), "not-an-object-id", ""):
        patch(service, {}, session_id)
    assert [call[0] for call in sessions.patched] == [
        SESSION_ID, SESSION_ID.upper(), "not-an-object-id", "",
    ]


def test_patch_forwards_only_supplied_known_fields_and_separates_extras(writes):
    service, sessions = writes
    patch(service, {
        "status": "COMPLETED",
        "completion_time": "2026-10-01T11:18:04.500999+02:00",
        "last_step_executed": ["pair-actions", "pair-actions", "", "$status"],
        "execution_outcome": {"defect_count": 0, "unknown": {"nested": [None, -5]}},
        **deepcopy(ARBITRARY_EXTRAS),
    })
    session_id, known, extras = sessions.patched[0]
    assert session_id == SESSION_ID
    assert known == {
        "status": "COMPLETED",
        "completion_time": datetime(2026, 10, 1, 9, 18, 4, 500000, tzinfo=timezone.utc),
        "last_step_executed": ["pair-actions", "pair-actions", "", "$status"],
        "execution_outcome": {"defect_count": 0, "unknown": {"nested": [None, -5]}},
    }
    assert isinstance(known["completion_time"], datetime)
    # A flat `metadata` key stays an ordinary extra; it is not promoted or merged.
    assert extras == ARBITRARY_EXTRAS
    assert extras["metadata"] == {"nested": "client supplied"}
    assert set(known) & set(extras) == set()


@pytest.mark.parametrize(
    ("body", "expected_known"),
    [
        ({"status": "FAILED"}, {"status": "FAILED"}),
        ({"completion_time": None}, {"completion_time": None}),
        ({"execution_outcome": None}, {"execution_outcome": None}),
        ({"last_step_executed": []}, {"last_step_executed": []}),
        ({"execution_outcome": {}}, {"execution_outcome": {}}),
        ({"execution_outcome": {"gap_count": 2**63 - 1}}, {"execution_outcome": {"gap_count": 2**63 - 1}}),
    ],
)
def test_patch_keeps_omission_and_explicit_null_distinct(writes, body, expected_known):
    service, sessions = writes
    patch(service, body)
    _, known, extras = sessions.patched[0]
    assert known == expected_known
    assert extras == {}
    # Fields the caller omitted are absent, never defaulted.
    assert set(known) == set(body)


def test_terminal_status_alone_does_not_synthesize_other_values(writes):
    service, sessions = writes
    patch(service, {"status": "COMPLETED"})
    _, known, extras = sessions.patched[0]
    assert known == {"status": "COMPLETED"}
    assert "completion_time" not in known and "execution_outcome" not in known
    assert "last_step_executed" not in known
    assert extras == {}
    assert FrozenClock.calls == []


def test_patch_outcomes_never_impute_zeros_or_aggregate_runs(writes):
    service, sessions = writes
    patch(service, {"execution_outcome": {"defect_count": 2}})
    _, known, _ = sessions.patched[0]
    assert known["execution_outcome"] == {"defect_count": 2}
    assert "gap_count" not in known["execution_outcome"]
    assert "contract_ingredient_count" not in known["execution_outcome"]


@pytest.mark.parametrize("field", ["status", "last_step_executed"])
def test_patch_rejects_explicit_null_for_non_nullable_fields(writes, field):
    service, sessions = writes
    expect_error(ErrorCode.INVALID_FIELD, patch, service, {field: None})
    assert sessions.patched == []


@pytest.mark.parametrize(
    "body",
    [
        {"status": "IN_PROGRESS"}, {"status": "completed"}, {"status": ""}, {"status": 1},
        {"status": True}, {"status": ["COMPLETED"]},
        {"last_step_executed": "pair-actions"}, {"last_step_executed": {}},
        {"last_step_executed": ["ok", 1]}, {"last_step_executed": ["ok", None]},
        {"last_step_executed": ["ok", True]}, {"last_step_executed": [["nested"]]},
        {"execution_outcome": []}, {"execution_outcome": "none"}, {"execution_outcome": 1},
        {"execution_outcome": True},
        {"execution_outcome": {"defect_count": -1}},
        {"execution_outcome": {"defect_count": "1"}},
        {"execution_outcome": {"defect_count": 1.0}},
        {"execution_outcome": {"defect_count": True}},
        {"execution_outcome": {"defect_count": None}},
        {"execution_outcome": {"gap_count": 2**63 - 1, "defect_count": -1}},
        {"completion_time": "2026-10-01T09:18:04"}, {"completion_time": 1790000000},
    ],
)
def test_patch_rejects_invalid_known_values_without_coercion(writes, body):
    service, sessions = writes
    expect_error(ErrorCode.INVALID_FIELD, patch, service, body)
    assert sessions.patched == []


@pytest.mark.parametrize("field", sorted(SESSION_PATCH_RESERVED_FIELDS))
def test_patch_rejects_each_reserved_field(writes, field):
    service, sessions = writes
    expect_error(ErrorCode.FORBIDDEN_FIELD, patch, service, {field: None})
    expect_error(ErrorCode.FORBIDDEN_FIELD, patch, service, {"status": "FAILED", field: "value"})
    assert sessions.patched == []


@pytest.mark.parametrize(
    "value",
    [
        STARTED_AT_INPUT, "2026-10-02T09:07:04Z", "not-a-timestamp",
        "2026-10-01T09:07:04", None, 1790000000, True, [], {},
    ],
)
def test_patch_rejects_started_at_without_forwarding_any_updates(writes, value):
    service, sessions = writes
    create(service, {"started_at": STARTED_AT_INPUT, "boundary": "original"})
    original = deepcopy(sessions.created[0])
    body = {"started_at": value, "status": "COMPLETED", "boundary": "replacement"}
    snapshot = deepcopy(body)

    expect_error(ErrorCode.FORBIDDEN_FIELD, patch, service, body)

    assert sessions.patched == []
    assert sessions.created == [original]
    assert body == snapshot


def test_patch_rejects_started_at_before_validating_other_known_fields(writes):
    service, sessions = writes
    expect_error(
        ErrorCode.FORBIDDEN_FIELD, patch, service,
        {"started_at": STARTED_AT_INPUT, "status": "not-a-status"},
    )
    assert sessions.patched == []


def test_patch_preserves_nested_started_at_as_data(writes):
    service, sessions = writes
    extras = {
        "metadata": {"started_at": "not-a-timestamp"},
        "trace": [{"started_at": None}],
    }
    outcome = {"defect_count": 0, "started_at": {"$set": "$status"}}

    assert patch(service, {"execution_outcome": outcome, **extras}) == SESSION_ID

    assert sessions.patched == [(SESSION_ID, {"execution_outcome": outcome}, extras)]


@pytest.mark.parametrize(
    ("code", "body"),
    [
        (ErrorCode.VALUE_OUT_OF_RANGE, {"huge": 2**63}),
        (ErrorCode.NON_FINITE_NUMBER, {"value": float("inf")}),
        (ErrorCode.INVALID_KEY, {"a\x00b": 1}),
        (ErrorCode.INVALID_FIELD, {"text": "\ud800"}),
    ],
)
def test_patch_rejects_invalid_raw_values_before_reserved_fields_and_persistence(writes, code, body):
    service, sessions = writes
    expect_error(code, patch, service, {"started_at": STARTED_AT_INPUT, **body})
    assert sessions.patched == []


@pytest.mark.parametrize(
    ("body_builder", "levels"),
    [
        (lambda value: {"extra": value}, 99),
        (lambda value: {"metadata": {"extra": value}}, 98),
        (lambda value: {"execution_outcome": {"unknown": value}}, 99),
    ],
)
def test_patch_rejects_values_that_would_exceed_stored_depth(writes, body_builder, levels):
    service, sessions = writes
    accepted: object = 0
    for _ in range(levels - 1):
        accepted = {"k": accepted}
    patch(service, body_builder(accepted))
    assert len(sessions.patched) == 1
    expect_error(ErrorCode.PAYLOAD_TOO_DEEP, patch, service, body_builder({"k": accepted}))
    assert len(sessions.patched) == 1


def test_patch_does_not_alias_or_mutate_caller_owned_values(writes):
    service, sessions = writes
    body = {
        "last_step_executed": ["pair-actions"],
        "execution_outcome": {"unknown": {"nested": [1, 2]}},
        "invoked_by": {"name": "Operator"},
    }
    snapshot = deepcopy(body)
    patch(service, body)
    _, known, extras = sessions.patched[0]
    known["last_step_executed"].append("mutated")
    known["execution_outcome"]["unknown"]["nested"].append(99)
    extras["invoked_by"]["name"] = "Mutated by the driver"
    assert body == snapshot


@pytest.mark.parametrize(
    "failure",
    [
        ApplicationError(ErrorCode.SESSION_NOT_FOUND),
        ApplicationError(ErrorCode.SESSION_NOT_OPEN),
        ApplicationError(ErrorCode.DOCUMENT_TOO_LARGE),
        ApplicationError(ErrorCode.INTERNAL_ERROR),
    ],
)
def test_patch_propagates_repository_errors_without_extra_reads(failure):
    sessions = RecordingSessionRepository(failure=failure)
    service = SessionService(sessions, UnusedRunRepository())
    expect_error(failure.code, patch, service, {"status": "COMPLETED"})
    assert len(sessions.patched) == 1


def test_patch_returns_the_repository_identifier(writes):
    service, _ = writes
    sessions = RecordingSessionRepository(session_id="68df8b00aef4d8537282f0ff")
    other = SessionService(sessions, UnusedRunRepository())
    assert patch(other, {"status": "FAILED"}) == "68df8b00aef4d8537282f0ff"
    assert create(service, {"started_at": STARTED_AT_INPUT}) == SESSION_ID


def test_writes_accept_timestamps_from_any_offset_without_clock_dependence(writes):
    service, sessions = writes
    body = {"started_at": datetime(2026, 10, 1, 9, 7, 4, tzinfo=timezone(timedelta(hours=-7))).isoformat()}
    create(service, body)
    assert sessions.created[0]["started_at"] == datetime(2026, 10, 1, 16, 7, 4, tzinfo=timezone.utc)
    assert sessions.created[0]["received_at"] == STORED_RECEIVED_AT
