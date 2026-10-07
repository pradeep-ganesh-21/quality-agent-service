from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.errors import ApplicationError, ErrorCode
from app.main import create_app
from app.repositories.protocols import RunRepository, SessionRepository
from app.services.mapping import SESSION_SUMMARY_FIELDS

SESSION_ID = "68df8b00aef4d8537282f001"
RUN_ID = "68df8b00aef4d8537282f002"
TIMESTAMP = datetime(2026, 10, 1, 11, 7, 4, 123456, tzinfo=timezone(timedelta(hours=2)))
SERIALIZED_TIMESTAMP = "2026-10-01T09:07:04.123Z"
INVALID_FIELD = {"error": {"code": "invalid_field", "message": "A request field is invalid."}}
INTERNAL_ERROR = {
    "error": {"code": "internal_error", "message": "The server could not complete the request."}
}


def summary_record():
    return {
        "session_id": SESSION_ID,
        "schema_version": 1,
        "started_at": TIMESTAMP,
        "received_at": TIMESTAMP,
        "status": "IN_PROGRESS",
        "completion_time": None,
        "last_step_executed": [],
        "execution_outcome": None,
    }


@pytest.fixture
def api_client(monkeypatch):
    sessions = AsyncMock(spec=SessionRepository)
    sessions.list_all.return_value = []
    sessions.get.return_value = None
    runs = AsyncMock(spec=RunRepository)
    runs.list_for_session.return_value = []

    @asynccontextmanager
    async def fake_runtime(uri, database_name):
        yield SimpleNamespace(sessions=sessions, runs=runs)

    monkeypatch.setattr("app.main.mongo_runtime", fake_runtime)
    settings = Settings(mongo_uri="mongodb://unit-test.invalid", mongo_db_name="unit")
    with TestClient(create_app(settings)) as client:
        yield client, sessions, runs


def test_default_list_retains_exact_eight_field_response(api_client):
    client, sessions, runs = api_client
    sessions.list_all.return_value = [summary_record()]
    response = client.get("/v1/sessions")
    assert response.status_code == 200
    assert response.json() == [{
        **summary_record(),
        "started_at": SERIALIZED_TIMESTAMP,
        "received_at": SERIALIZED_TIMESTAMP,
    }]
    assert set(response.json()[0]) == set(SESSION_SUMMARY_FIELDS)
    sessions.list_all.assert_awaited_once_with(SESSION_SUMMARY_FIELDS)
    assert runs.mock_calls == []


def test_repeated_fields_produce_nested_partial_response(api_client):
    client, sessions, runs = api_client
    sessions.list_all.return_value = [{
        "session_id": SESSION_ID,
        "started_at": TIMESTAMP,
        "metadata": {"invoked_by": {"name": "Operator"}, "boundary": "checkout"},
    }]
    response = client.get("/v1/sessions", params=[
        ("fields", "started_at"),
        ("fields", "metadata.invoked_by.name"),
        ("fields", "metadata.boundary"),
    ])
    assert response.status_code == 200
    assert response.json() == [{
        "session_id": SESSION_ID,
        "started_at": SERIALIZED_TIMESTAMP,
        "metadata": {"invoked_by": {"name": "Operator"}, "boundary": "checkout"},
    }]
    sessions.list_all.assert_awaited_once_with((
        "metadata.boundary", "metadata.invoked_by.name", "session_id", "started_at",
    ))
    assert runs.mock_calls == []


def test_explicit_default_fields_match_the_unqualified_response(api_client):
    client, sessions, _ = api_client
    sessions.list_all.return_value = [summary_record()]
    default = client.get("/v1/sessions")
    selected = client.get("/v1/sessions", params=[("fields", field) for field in SESSION_SUMMARY_FIELDS])
    assert default.status_code == selected.status_code == 200
    assert default.content == selected.content


@pytest.mark.parametrize("selector", [None, "session_id", "metadata.boundary"])
def test_empty_list_is_always_an_empty_array(api_client, selector):
    client, _, _ = api_client
    response = client.get("/v1/sessions", params={} if selector is None else {"fields": selector})
    assert response.status_code == 200
    assert response.json() == []


def test_id_only_list_is_unbounded_and_retains_repository_order(api_client):
    client, sessions, _ = api_client
    records = [{"session_id": f"{index:024x}"} for index in range(1100, 0, -1)]
    sessions.list_all.return_value = records
    response = client.get("/v1/sessions?fields=session_id")
    assert response.status_code == 200
    assert response.json() == records
    sessions.list_all.assert_awaited_once_with(("session_id",))


def test_explicit_null_and_absent_values_are_distinct(api_client):
    client, sessions, _ = api_client
    records = [
        {"session_id": SESSION_ID},
        {"session_id": SESSION_ID, "completion_time": None, "execution_outcome": None},
        {"session_id": SESSION_ID, "metadata": {}},
        {"session_id": SESSION_ID, "metadata": {"boundary": None}},
        {"session_id": SESSION_ID, "execution_outcome": {"defect_count": 0}},
    ]
    sessions.list_all.return_value = records
    response = client.get("/v1/sessions", params=[
        ("fields", "completion_time"), ("fields", "execution_outcome"),
        ("fields", "metadata.boundary"),
    ])
    assert response.status_code == 200
    assert response.json() == records


@pytest.mark.parametrize("field", ["started_at", "received_at", "completion_time"])
@pytest.mark.parametrize("microsecond", [0, 123456])
def test_each_projected_timestamp_uses_exact_utc_milliseconds(api_client, field, microsecond):
    client, sessions, _ = api_client
    timestamp = TIMESTAMP.replace(microsecond=microsecond)
    sessions.list_all.return_value = [{"session_id": SESSION_ID, field: timestamp}]
    response = client.get("/v1/sessions", params={"fields": field})
    assert response.status_code == 200
    expected = "2026-10-01T09:07:04.000Z" if microsecond == 0 else SERIALIZED_TIMESTAMP
    assert response.json() == [{"session_id": SESSION_ID, field: expected}]
    assert sessions.list_all.return_value[0][field] == timestamp


def test_complete_parent_selection_preserves_unknown_json(api_client):
    client, sessions, _ = api_client
    metadata = {
        "invoked_by": ["arbitrary", None],
        "recorded_by": 17,
        "boundary": {"a.b": {"$set": "$status", "_id": "nested"}},
        "array": [None, False, {}, -9223372036854775808],
        "large": 9223372036854775807,
        "__proto__": {"name": "data"},
        "timestamp_text": "2026-10-01T11:00:00+02:00",
    }
    sessions.list_all.return_value = [{"session_id": SESSION_ID, "metadata": metadata}]
    response = client.get("/v1/sessions", params=[
        ("fields", "metadata.boundary.a"), ("fields", "metadata"), ("fields", "metadata"),
    ])
    assert response.status_code == 200
    assert response.json() == [{"session_id": SESSION_ID, "metadata": metadata}]
    sessions.list_all.assert_awaited_once_with(("metadata", "session_id"))


@pytest.mark.parametrize(
    "fields",
    [[""], ["runs"], ["_id"], ["started_at.year"], ["metadata."], ["metadata..name"],
     ["metadata.\x00name"], ["metadata.$where"], ["status,started_at"],
     ["metadata", "metadata.$where"], ["metadata.$where", "metadata"]],
)
def test_invalid_query_fields_are_sanitized_before_repository_access(api_client, fields):
    client, sessions, runs = api_client
    response = client.get("/v1/sessions", params=[("fields", field) for field in fields])
    assert response.status_code == 400
    assert response.json() == INVALID_FIELD
    assert sessions.mock_calls == []
    assert runs.mock_calls == []


@pytest.mark.parametrize("field", list(SESSION_SUMMARY_FIELDS))
def test_default_list_still_rejects_incomplete_records(api_client, field):
    client, sessions, _ = api_client
    record = summary_record()
    del record[field]
    sessions.list_all.return_value = [record]
    response = client.get("/v1/sessions")
    assert response.status_code == 500
    assert response.json() == INTERNAL_ERROR


@pytest.mark.parametrize(
    "record",
    [
        {}, {"session_id": "invalid"},
        {"session_id": SESSION_ID, "schema_version": "1"},
        {"session_id": SESSION_ID, "status": "INVALID"},
        {"session_id": SESSION_ID, "started_at": TIMESTAMP.replace(tzinfo=None)},
        {"session_id": SESSION_ID, "runs": []},
        {"session_id": SESSION_ID, "started_at": "invalid timestamp"},
    ],
)
def test_projected_response_keeps_present_fields_strict(api_client, record):
    client, sessions, _ = api_client
    sessions.list_all.return_value = [record]
    response = client.get("/v1/sessions?fields=session_id")
    assert response.status_code == 500
    assert response.json() == INTERNAL_ERROR


@pytest.mark.parametrize(
    "field", ["schema_version", "started_at", "received_at", "status", "last_step_executed", "metadata"],
)
def test_selected_nonnullable_fields_reject_explicit_null(api_client, field):
    client, sessions, _ = api_client
    sessions.list_all.return_value = [{"session_id": SESSION_ID, field: None}]
    response = client.get("/v1/sessions", params={"fields": field})
    assert response.status_code == 500
    assert response.json() == INTERNAL_ERROR


def test_default_list_rejects_accidental_metadata_instead_of_exposing_it(api_client):
    client, sessions, _ = api_client
    sessions.list_all.return_value = [{**summary_record(), "metadata": {"private": "value"}}]
    response = client.get("/v1/sessions")
    assert response.status_code == 500
    assert response.json() == INTERNAL_ERROR


def test_detail_remains_complete_after_selected_list_read(api_client):
    client, sessions, runs = api_client
    sessions.list_all.return_value = [{"session_id": SESSION_ID}]
    assert client.get("/v1/sessions?fields=session_id").json() == [{"session_id": SESSION_ID}]

    metadata = {"invoked_by": {"name": "Operator", "email": "operator@example.invalid"}}
    sessions.get.return_value = {**summary_record(), "metadata": metadata}
    run = {
        "run_id": RUN_ID, "session_id": SESSION_ID, "schema_version": 1,
        "step": "pair-actions", "command": "pair", "verdict": "NEW_VERDICT",
        "occurred_at": TIMESTAMP, "received_at": TIMESTAMP,
        "details": {"a.b": {"$set": "$status"}},
    }
    runs.list_for_session.return_value = [run]
    response = client.get(f"/v1/sessions/{SESSION_ID.upper()}")
    assert response.status_code == 200
    assert response.json() == {
        **summary_record(),
        "started_at": SERIALIZED_TIMESTAMP, "received_at": SERIALIZED_TIMESTAMP,
        "metadata": metadata,
        "runs": [{**run, "occurred_at": SERIALIZED_TIMESTAMP, "received_at": SERIALIZED_TIMESTAMP}],
    }
    sessions.get.assert_awaited_once_with(SESSION_ID.upper())
    runs.list_for_session.assert_awaited_once_with(SESSION_ID)


def test_detail_with_no_runs_keeps_empty_list(api_client):
    client, sessions, _ = api_client
    sessions.get.return_value = {**summary_record(), "metadata": {}}
    response = client.get(f"/v1/sessions/{SESSION_ID}")
    assert response.status_code == 200
    assert response.json()["runs"] == []


def test_missing_detail_does_not_read_runs(api_client):
    client, _, runs = api_client
    response = client.get(f"/v1/sessions/{SESSION_ID}")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "session_not_found"
    assert runs.mock_calls == []


def test_incomplete_detail_still_fails_response_validation(api_client):
    client, sessions, _ = api_client
    sessions.get.return_value = {"session_id": SESSION_ID, "metadata": {}}
    response = client.get(f"/v1/sessions/{SESSION_ID}")
    assert response.status_code == 500
    assert response.json() == INTERNAL_ERROR


def test_list_database_error_retains_sanitized_application_envelope(api_client):
    client, sessions, _ = api_client
    sessions.list_all.side_effect = ApplicationError(ErrorCode.INTERNAL_ERROR)
    response = client.get("/v1/sessions?fields=metadata")
    assert response.status_code == 500
    assert response.json() == INTERNAL_ERROR
