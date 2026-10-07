import asyncio
from itertools import permutations
from unittest.mock import AsyncMock

import pytest

from app.errors import ApplicationError, ErrorCode
from app.repositories.protocols import (
    RunRepository,
    SessionListQuery,
    SessionPage,
    SessionRepository,
)
from app.schemas.sessions import SessionProjectionResponse, SessionSummaryResponse
from app.services.mapping import SESSION_SUMMARY_FIELDS, normalize_session_fields
from app.services.session_listing import DEFAULT_PAGE_SIZE
from app.services.session_service import SessionService


def test_default_fields_are_the_existing_eight_root_fields():
    assert normalize_session_fields(None) == (
        "session_id", "schema_version", "started_at", "received_at", "status",
        "completion_time", "last_step_executed", "execution_outcome",
    )


def test_selectable_roots_match_the_response_models():
    assert set(SessionSummaryResponse.model_fields) == set(SESSION_SUMMARY_FIELDS)
    assert set(SessionProjectionResponse.model_fields) == set(SESSION_SUMMARY_FIELDS) | {"metadata"}
    for field in SessionProjectionResponse.model_fields:
        assert set(normalize_session_fields([field])) == {"session_id", field}


@pytest.mark.parametrize("field", [*SESSION_SUMMARY_FIELDS, "metadata"])
def test_each_selectable_root_always_includes_session_id(field):
    assert set(normalize_session_fields([field])) == {field, "session_id"}


@pytest.mark.parametrize(
    "field",
    [
        "metadata.invoked_by.name", "metadata.boundary", "metadata._id",
        "metadata.__proto__.name", "metadata.a-b", "metadata.a$b",
        "metadata.display name", "metadata.日本語", "execution_outcome.defect_count",
        "execution_outcome.extra.nested",
    ],
)
def test_nested_paths_remain_application_paths(field):
    assert set(normalize_session_fields([field])) == {field, "session_id"}


def test_selection_is_deduplicated_and_does_not_mutate_input():
    fields = ["metadata.boundary", "started_at", "metadata.boundary", "session_id"]
    original = fields.copy()
    assert normalize_session_fields(fields) == (
        "metadata.boundary", "session_id", "started_at",
    )
    assert fields == original


def test_parents_collapse_descendants_independently_of_input_order():
    paths = ["metadata.invoked_by.name", "metadata", "metadata.invoked_by"]
    for fields in permutations(paths):
        assert normalize_session_fields(fields) == ("metadata", "session_id")


def test_collapse_uses_components_not_textual_prefixes():
    assert normalize_session_fields([
        "metadata.a.child", "metadata.ab", "metadata.a-b", "metadata.a",
        "execution_outcome.extra.count", "execution_outcome",
    ]) == (
        "execution_outcome", "metadata.a", "metadata.a-b", "metadata.ab", "session_id",
    )


@pytest.mark.parametrize(
    "fields",
    [
        [], [""], [" "], ["_id"], ["runs"], ["runs.step"], ["boundary"],
        ["session_id.name"], ["started_at.year"], ["last_step_executed.name"],
        ["metadata."], [".metadata"], ["metadata..name"], ["metadata.\x00name"],
        ["metadata.\ud800"], ["$where"], ["metadata.$where"], ["metadata.a.$"],
        ["metadata.$[item].name"], ["metadata", "metadata.$where"],
        ["metadata.$where", "metadata"], ["execution_outcome.$slice"],
        ["status,started_at"], ["metadata.name", "runs"], [None], "status",
    ],
)
def test_invalid_selection_is_rejected_by_normalization(fields):
    with pytest.raises(ApplicationError) as caught:
        normalize_session_fields(fields)
    assert caught.value.code == ErrorCode.INVALID_FIELD


@pytest.mark.parametrize(
    "fields",
    [
        [""], ["runs"], ["metadata.$where"], ["status,started_at"],
        ["metadata", "metadata.$where"], [None],
    ],
)
def test_invalid_selection_is_rejected_before_any_repository_call(fields):
    sessions = AsyncMock(spec=SessionRepository)
    runs = AsyncMock(spec=RunRepository)
    service = SessionService(sessions, runs)
    with pytest.raises(ApplicationError) as caught:
        asyncio.run(service.list_sessions([("fields", field) for field in fields]))
    assert caught.value.code == ErrorCode.INVALID_FIELD
    assert str(caught.value) == "invalid_field"
    assert sessions.mock_calls == []
    assert runs.mock_calls == []


@pytest.mark.parametrize(
    ("fields", "expected"),
    [
        (None, SESSION_SUMMARY_FIELDS),
        (["session_id"], ("session_id",)),
        (["metadata.name", "metadata", "status"], ("metadata", "session_id", "status")),
    ],
)
def test_service_passes_normalized_fields_through_the_protocol(fields, expected):
    sessions = AsyncMock(spec=SessionRepository)
    records = [{"session_id": "68df8b00aef4d8537282f001"}]
    sessions.list_page.return_value = SessionPage(items=records, total_count=1)
    runs = AsyncMock(spec=RunRepository)
    service = SessionService(sessions, runs)

    parameters = None if fields is None else [("fields", field) for field in fields]
    result = asyncio.run(service.list_sessions(parameters))
    assert result.items is records
    assert result.projected is (fields is not None)
    sessions.list_page.assert_awaited_once_with(
        SessionListQuery(fields=expected, page_size=DEFAULT_PAGE_SIZE)
    )
    sessions.get.assert_not_awaited()
    assert runs.mock_calls == []

