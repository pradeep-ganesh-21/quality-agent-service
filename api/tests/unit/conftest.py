from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.repositories.protocols import (
    PageAnchor,
    RunRepository,
    SessionPage,
    SessionRepository,
)

SESSION_ID = "68df8b00aef4d8537282f001"
RUN_ID = "68df8b00aef4d8537282f002"
TIMESTAMP = datetime(2026, 10, 1, 11, 7, 4, 123456, tzinfo=timezone(timedelta(hours=2)))
SERIALIZED_TIMESTAMP = "2026-10-01T09:07:04.123Z"
RECEIVED_AT = datetime(2026, 10, 1, 9, 7, 5, 456789, tzinfo=timezone.utc)
DEFAULT_PAGE_SIZE = 25


def error(code: str, message: str) -> dict[str, dict[str, str]]:
    return {"error": {"code": code, "message": message}}


INVALID_JSON = error("invalid_json", "Request body is not valid JSON.")
INVALID_BODY = error("invalid_body", "Request body must be a JSON object.")
FORBIDDEN_FIELD = error("forbidden_field", "Request contains a reserved top-level field.")
MISSING_FIELD = error("missing_field", "A required field is missing.")
INVALID_FIELD = error("invalid_field", "A request field is invalid.")
INVALID_KEY = error("invalid_key", "Object keys must not contain NUL.")
PAYLOAD_TOO_DEEP = error(
    "payload_too_deep", "The stored document would exceed 100 nesting levels."
)
NON_FINITE_NUMBER = error("non_finite_number", "Numbers must be finite.")
VALUE_OUT_OF_RANGE = error("value_out_of_range", "An integer is outside the supported range.")
SESSION_NOT_FOUND = error("session_not_found", "Session not found.")
SESSION_NOT_OPEN = error("session_not_open", "Session is not open for updates.")
DOCUMENT_TOO_LARGE = error(
    "document_too_large", "The stored document would exceed the MongoDB size limit."
)
UNSUPPORTED_MEDIA_TYPE = error("unsupported_media_type", "Content-Type must be application/json.")
INTERNAL_ERROR = error("internal_error", "The server could not complete the request.")


def summary_record() -> dict[str, object]:
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


def session_page(
    *items: dict[str, object],
    total_count: int | None = None,
    has_newer: bool = False,
    has_older: bool = False,
) -> SessionPage:
    """Build a repository page whose anchors are consistent with its records."""
    records = list(items)
    anchor = PageAnchor(started_at=TIMESTAMP, session_id=SESSION_ID)
    return SessionPage(
        items=records,
        total_count=len(records) if total_count is None else total_count,
        newest=anchor if records else None,
        oldest=anchor if records else None,
        has_newer=has_newer,
        has_older=has_older,
    )


def page_response(
    items: list[dict[str, object]],
    *,
    page_size: int = DEFAULT_PAGE_SIZE,
    total_count: int | None = None,
    next_cursor: str | None = None,
    previous_cursor: str | None = None,
) -> dict[str, object]:
    return {
        "items": items,
        "page_size": page_size,
        "total_count": len(items) if total_count is None else total_count,
        "next_cursor": next_cursor,
        "previous_cursor": previous_cursor,
    }


@pytest.fixture
def api_client(monkeypatch, request):
    """Exercise the real app and controllers with protocol-shaped repository mocks.

    Parametrize indirectly with False to inspect sanitized responses for exceptions
    that Starlette would otherwise re-raise into the test.
    """
    sessions = AsyncMock(spec=SessionRepository)
    sessions.list_page.return_value = session_page()
    sessions.get.return_value = None
    sessions.create.return_value = SESSION_ID
    sessions.patch_open_session.return_value = SESSION_ID
    runs = AsyncMock(spec=RunRepository)
    runs.list_for_session.return_value = []

    @asynccontextmanager
    async def fake_runtime(uri, database_name):
        yield SimpleNamespace(sessions=sessions, runs=runs)

    monkeypatch.setattr("app.main.mongo_runtime", fake_runtime)
    settings = Settings(mongo_uri="mongodb://unit-test.invalid", mongo_db_name="unit")
    raise_server_exceptions = getattr(request, "param", True)
    with TestClient(
        create_app(settings), raise_server_exceptions=raise_server_exceptions
    ) as client:
        yield client, sessions, runs
