"""HTTP contracts for session creation and open partial updates."""

import json

import pytest

from app.errors import ApplicationError, ErrorCode
from app.services.mapping import SESSION_CREATE_RESERVED_FIELDS, SESSION_PATCH_RESERVED_FIELDS
from conftest import (
    DOCUMENT_TOO_LARGE,
    FORBIDDEN_FIELD,
    INTERNAL_ERROR,
    INVALID_BODY,
    INVALID_FIELD,
    INVALID_JSON,
    INVALID_KEY,
    MISSING_FIELD,
    NON_FINITE_NUMBER,
    PAYLOAD_TOO_DEEP,
    SESSION_ID,
    SESSION_NOT_FOUND,
    SESSION_NOT_OPEN,
    UNSUPPORTED_MEDIA_TYPE,
    VALUE_OUT_OF_RANGE,
)

JSON_HEADERS = {"Content-Type": "application/json"}
STARTED_AT = "2026-10-01T09:07:04Z"
PATCH_PATH = f"/v1/sessions/{SESSION_ID}"


def post(client, body=None, *, raw=None, headers=JSON_HEADERS):
    content = raw if raw is not None else json.dumps(body).encode()
    return client.post("/v1/sessions", content=content, headers=headers)


def patch(client, body=None, *, raw=None, headers=JSON_HEADERS, path=PATCH_PATH):
    content = raw if raw is not None else json.dumps(body).encode()
    return client.patch(path, content=content, headers=headers)


def test_create_returns_only_the_server_generated_identifier(api_client):
    client, sessions, runs = api_client
    response = post(client, {"started_at": STARTED_AT, "boundary": "checkout"})
    assert response.status_code == 201
    assert response.json() == {"session_id": SESSION_ID}
    sessions.create.assert_awaited_once()
    assert sessions.patch_open_session.await_count == 0
    assert runs.mock_calls == []


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"status": "COMPLETED"},
        {"status": "FAILED", "completion_time": None},
        {"last_step_executed": ["pair-actions"], "invoked_by": {"name": "Operator"}},
        {"execution_outcome": {"defect_count": 0, "unknown": {"nested": True}}},
        {"started_at": STARTED_AT},
    ],
)
def test_patch_accepts_open_partial_updates_including_an_empty_object(api_client, body):
    client, sessions, runs = api_client
    response = patch(client, body)
    assert response.status_code == 200
    assert response.json() == {"session_id": SESSION_ID}
    sessions.patch_open_session.assert_awaited_once()
    assert sessions.patch_open_session.await_args.args[0] == SESSION_ID
    assert sessions.create.await_count == 0
    assert runs.mock_calls == []


@pytest.mark.parametrize("method", ["post", "patch"])
@pytest.mark.parametrize(
    "content_type",
    ["", "text/plain", "application/xml", "application/json-patch+json", "multipart/form-data"],
)
@pytest.mark.parametrize("raw", [None, b"", b"{", b"[]", b'{"value": NaN}'])
def test_media_type_is_verified_before_the_body_is_parsed(
    api_client, method, content_type, raw
):
    client, sessions, _ = api_client
    send = post if method == "post" else patch
    headers = {} if content_type == "" else {"Content-Type": content_type}
    body = {"started_at": STARTED_AT} if raw is None else None
    response = send(client, body, raw=raw, headers=headers)
    assert response.status_code == 415
    assert response.json() == UNSUPPORTED_MEDIA_TYPE
    assert sessions.mock_calls == []


@pytest.mark.parametrize("method", ["post", "patch"])
@pytest.mark.parametrize("charset", ["application/json; charset=utf-8", "APPLICATION/JSON"])
def test_media_type_parameters_and_case_are_accepted(api_client, method, charset):
    client, _, _ = api_client
    send = post if method == "post" else patch
    body = {"started_at": STARTED_AT} if method == "post" else {}
    response = send(client, body, headers={"Content-Type": charset})
    assert response.status_code == (201 if method == "post" else 200)


@pytest.mark.parametrize("method", ["post", "patch"])
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (b"", INVALID_JSON),
        (b"   ", INVALID_JSON),
        (b"{", INVALID_JSON),
        (b'{"started_at": }', INVALID_JSON),
        (b"\xff\xfe", INVALID_JSON),
        (b"[]", INVALID_BODY),
        (b"null", INVALID_BODY),
        (b'"text"', INVALID_BODY),
        (b"7", INVALID_BODY),
        (b'{"value": NaN}', NON_FINITE_NUMBER),
        (b'{"value": Infinity}', NON_FINITE_NUMBER),
        (b'{"value": 1e999}', NON_FINITE_NUMBER),
        (b'{"value": 9223372036854775808}', VALUE_OUT_OF_RANGE),
        (b'{"value": -9223372036854775809}', VALUE_OUT_OF_RANGE),
        (b'{"a\\u0000b": 1}', INVALID_KEY),
        (b'{"nested": {"a\\u0000b": 1}}', INVALID_KEY),
        (b'{"text": "\\ud800"}', INVALID_FIELD),
    ],
)
def test_malformed_bodies_and_invalid_values_are_rejected_before_persistence(
    api_client, method, raw, expected
):
    client, sessions, _ = api_client
    send = post if method == "post" else patch
    response = send(client, raw=raw)
    assert response.status_code == 400
    assert response.json() == expected
    assert sessions.mock_calls == []


@pytest.mark.parametrize("field", sorted(SESSION_CREATE_RESERVED_FIELDS))
def test_create_rejects_every_reserved_top_level_field(api_client, field):
    client, sessions, _ = api_client
    response = post(client, {"started_at": STARTED_AT, field: None})
    assert response.status_code == 400
    assert response.json() == FORBIDDEN_FIELD
    assert sessions.mock_calls == []


@pytest.mark.parametrize("field", sorted(SESSION_PATCH_RESERVED_FIELDS))
def test_patch_rejects_every_reserved_top_level_field(api_client, field):
    client, sessions, _ = api_client
    response = patch(client, {field: None, "status": "COMPLETED"})
    assert response.status_code == 400
    assert response.json() == FORBIDDEN_FIELD
    assert sessions.mock_calls == []


def test_patch_allows_the_session_root_fields_that_creation_reserves(api_client):
    client, sessions, _ = api_client
    response = patch(client, {
        "status": "COMPLETED",
        "completion_time": "2026-10-01T09:18:04Z",
        "last_step_executed": ["pair-actions"],
        "execution_outcome": {"gap_count": 1},
    })
    assert response.status_code == 200
    sessions.patch_open_session.assert_awaited_once()


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ({}, MISSING_FIELD),
        ({"boundary": "checkout"}, MISSING_FIELD),
        ({"started_at": None}, INVALID_FIELD),
        ({"started_at": "2026-10-01T09:07:04"}, INVALID_FIELD),
        ({"started_at": "2026-10-01"}, INVALID_FIELD),
        ({"started_at": 1790000000}, INVALID_FIELD),
        ({"started_at": True}, INVALID_FIELD),
        ({"started_at": ["2026-10-01T09:07:04Z"]}, INVALID_FIELD),
    ],
)
def test_create_requires_a_valid_offset_aware_started_at(api_client, body, expected):
    client, sessions, _ = api_client
    response = post(client, body)
    assert response.status_code == 400
    assert response.json() == expected
    assert sessions.mock_calls == []


@pytest.mark.parametrize(
    "body",
    [
        {"status": None}, {"status": "IN_PROGRESS"}, {"status": "completed"}, {"status": 1},
        {"last_step_executed": None}, {"last_step_executed": "pair-actions"},
        {"last_step_executed": ["ok", 1]}, {"started_at": None},
        {"completion_time": "2026-10-01T09:18:04"},
        {"execution_outcome": []}, {"execution_outcome": {"defect_count": -1}},
        {"execution_outcome": {"defect_count": "2"}},
        {"execution_outcome": {"gap_count": 9223372036854775807, "defect_count": 1.0}},
    ],
)
def test_patch_rejects_invalid_known_values(api_client, body):
    client, sessions, _ = api_client
    response = patch(client, body)
    assert response.status_code == 400
    assert response.json() == INVALID_FIELD
    assert sessions.mock_calls == []


@pytest.mark.parametrize("method", ["post", "patch"])
def test_payloads_that_would_exceed_stored_nesting_are_rejected(api_client, method):
    client, sessions, _ = api_client
    send = post if method == "post" else patch
    accepted: object = 0
    for _ in range(98):
        accepted = {"k": accepted}
    body = {"extra": accepted}
    if method == "post":
        body["started_at"] = STARTED_AT
    assert send(client, body).status_code == (201 if method == "post" else 200)

    body["extra"] = {"k": accepted}
    response = send(client, body)
    assert response.status_code == 400
    assert response.json() == PAYLOAD_TOO_DEEP


def test_create_preserves_arbitrary_metadata_through_the_http_boundary(api_client):
    client, sessions, _ = api_client
    extras = {
        "boundary": "checkout",
        "recorded_by": {"name": "Agent", "email": "agent@example.invalid"},
        "invoked_by": {"name": "Operator"},
        "run_id": "legacy-value",
        "metadata": {"nested": "client supplied"},
        "a.b": {"$set": "$status", "_id": "nested"},
        "limits": {"min": -9223372036854775808, "max": 9223372036854775807},
        "array": [None, True, 1, 1.5, "text"],
        "日本語": "値",
    }
    assert post(client, {"started_at": STARTED_AT, **extras}).status_code == 201
    document = sessions.create.await_args.args[0]
    assert document["metadata"] == extras
    assert document["metadata"]["metadata"] == {"nested": "client supplied"}
    assert document["status"] == "IN_PROGRESS"
    assert document["last_step_executed"] == []
    assert document["execution_outcome"] is None
    assert document["completion_time"] is None
    assert document["schema_version"] == 1


def test_patch_separates_known_values_from_arbitrary_metadata(api_client):
    client, sessions, _ = api_client
    response = patch(client, {
        "status": "COMPLETED",
        "last_step_executed": ["pair-actions"],
        "invoked_by": {"name": "New name"},
        "a.b": {"$set": "$status"},
    })
    assert response.status_code == 200
    _, known, extras = sessions.patch_open_session.await_args.args
    assert set(known) == {"status", "last_step_executed"}
    assert extras == {"invoked_by": {"name": "New name"}, "a.b": {"$set": "$status"}}


@pytest.mark.parametrize("method", ["post", "patch"])
@pytest.mark.parametrize(
    ("code", "status", "expected"),
    [
        (ErrorCode.DOCUMENT_TOO_LARGE, 413, DOCUMENT_TOO_LARGE),
        (ErrorCode.INVALID_FIELD, 400, INVALID_FIELD),
        (ErrorCode.INTERNAL_ERROR, 500, INTERNAL_ERROR),
    ],
)
def test_repository_write_failures_map_to_the_documented_envelopes(
    api_client, method, code, status, expected
):
    client, sessions, _ = api_client
    operation = sessions.create if method == "post" else sessions.patch_open_session
    operation.side_effect = ApplicationError(code)
    send = post if method == "post" else patch
    response = send(client, {"started_at": STARTED_AT} if method == "post" else {})
    assert response.status_code == status
    assert response.json() == expected
    assert operation.await_count == 1


@pytest.mark.parametrize("body", [{}, {"status": "COMPLETED"}])
@pytest.mark.parametrize(
    ("code", "status", "expected"),
    [
        (ErrorCode.SESSION_NOT_FOUND, 404, SESSION_NOT_FOUND),
        (ErrorCode.SESSION_NOT_OPEN, 409, SESSION_NOT_OPEN),
    ],
)
def test_patch_reports_missing_and_terminal_sessions_distinctly(
    api_client, body, code, status, expected
):
    client, sessions, _ = api_client
    sessions.patch_open_session.side_effect = ApplicationError(code)
    response = patch(client, body)
    assert response.status_code == status
    assert response.json() == expected
    assert sessions.patch_open_session.await_count == 1


@pytest.mark.parametrize(
    ("path", "expected_id"),
    [
        ("/v1/sessions/not-an-object-id", "not-an-object-id"),
        ("/v1/sessions/68df8b00aef4d8537282f0", "68df8b00aef4d8537282f0"),
        ("/v1/sessions/%3Cscript%3E", "<script>"),
        (f"/v1/sessions/{SESSION_ID.upper()}", SESSION_ID.upper()),
    ],
)
def test_patch_forwards_unusual_identifiers_for_adapter_validation(api_client, path, expected_id):
    client, sessions, _ = api_client
    sessions.patch_open_session.side_effect = ApplicationError(ErrorCode.SESSION_NOT_FOUND)
    response = patch(client, {}, path=path)
    assert response.status_code == 404
    assert response.json() == SESSION_NOT_FOUND
    assert sessions.patch_open_session.await_args.args[0] == expected_id


@pytest.mark.parametrize("api_client", [False], indirect=True)
@pytest.mark.parametrize("method", ["post", "patch"])
def test_unexpected_repository_exceptions_are_sanitized(api_client, method):
    client, sessions, _ = api_client
    operation = sessions.create if method == "post" else sessions.patch_open_session
    operation.side_effect = RuntimeError("sensitive driver details")
    send = post if method == "post" else patch
    response = send(client, {"started_at": STARTED_AT} if method == "post" else {})
    assert response.status_code == 500
    assert response.json() == INTERNAL_ERROR
    assert "sensitive" not in response.text


def test_invalid_request_responses_never_echo_supplied_values(api_client):
    client, _, _ = api_client
    response = post(client, raw=b'{"started_at": "not-a-timestamp", "secret": "private-value"}')
    assert response.status_code == 400
    assert response.json() == INVALID_FIELD
    assert "private-value" not in response.text and "not-a-timestamp" not in response.text


@pytest.mark.parametrize(
    ("method", "path"),
    [("put", PATCH_PATH), ("delete", PATCH_PATH), ("post", PATCH_PATH), ("patch", "/v1/sessions")],
)
def test_unsupported_write_methods_are_rejected_without_persistence(api_client, method, path):
    client, sessions, _ = api_client
    response = client.request(method, path, content=b"{}", headers=JSON_HEADERS)
    assert response.status_code == 405
    assert response.json()["error"]["code"] == "method_not_allowed"
    assert "allow" in response.headers
    assert sessions.mock_calls == []
