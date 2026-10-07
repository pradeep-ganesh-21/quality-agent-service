import asyncio
from base64 import urlsafe_b64decode, urlsafe_b64encode
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest

from app.errors import ApplicationError, ErrorCode
from app.repositories.protocols import (
    PageAnchor,
    PagePosition,
    RunRepository,
    SessionFilters,
    SessionPage,
    SessionRepository,
)
from app.services.session_listing import (
    DEFAULT_PAGE_SIZE,
    LIST_PARAMETERS,
    MAX_FILTER_TEXT_LENGTH,
    MAX_PAGE_SIZE,
    build_session_list_result,
    parse_session_list_request,
)
from app.services.session_service import SessionService
from conftest import INVALID_FIELD, SESSION_ID, page_response, session_page

OTHER_ID = "68df8b00aef4d8537282f099"
TIMESTAMP = datetime(2026, 10, 1, 9, 7, 4, tzinfo=timezone.utc)
LATER = TIMESTAMP + timedelta(hours=1)


def parse(**parameters):
    return parse_session_list_request(list(parameters.items()))


def cursors(parameters, page):
    """Mint the cursors a page would advertise for one parsed request."""
    return build_session_list_result(parse_session_list_request(parameters), page)


def anchored_page(
    *,
    newest: PageAnchor | None = None,
    oldest: PageAnchor | None = None,
    total_count: int = 2,
    has_newer: bool = False,
    has_older: bool = False,
) -> SessionPage:
    anchor = PageAnchor(started_at=TIMESTAMP, session_id=SESSION_ID)
    return SessionPage(
        items=[{"session_id": SESSION_ID}],
        total_count=total_count,
        newest=anchor if newest is None else newest,
        oldest=anchor if oldest is None else oldest,
        has_newer=has_newer,
        has_older=has_older,
    )


def test_no_parameters_selects_the_default_page_and_no_filters():
    request = parse()
    assert request.query.page_size == DEFAULT_PAGE_SIZE == 25
    assert request.query.filters == SessionFilters()
    assert request.query.position is None
    assert request.projected is False


def test_the_accepted_parameter_set_is_closed():
    assert LIST_PARAMETERS == {
        "fields", "status", "started_from", "started_before", "boundary",
        "invoked_by_email", "page_size", "cursor",
    }


@pytest.mark.parametrize(
    ("parameters", "expected"),
    [
        ({"status": "IN_PROGRESS"}, SessionFilters(status="IN_PROGRESS")),
        ({"status": "COMPLETED"}, SessionFilters(status="COMPLETED")),
        ({"status": "FAILED"}, SessionFilters(status="FAILED")),
        ({"boundary": "payments"}, SessionFilters(boundary_contains="payments")),
        # Filter text stays verbatim; escaping belongs to the repository adapter.
        ({"boundary": ".*$where"}, SessionFilters(boundary_contains=".*$where")),
        (
            {"invoked_by_email": "Ops@Example.Invalid"},
            SessionFilters(invoked_by_email="Ops@Example.Invalid"),
        ),
        (
            {"started_from": "2026-10-01T09:07:04Z"},
            SessionFilters(started_from=TIMESTAMP),
        ),
        (
            {"started_before": "2026-10-01T11:07:04+02:00"},
            SessionFilters(started_before=TIMESTAMP),
        ),
        (
            {"started_from": "2026-10-01T09:07:04.123456Z"},
            SessionFilters(started_from=TIMESTAMP.replace(microsecond=123000)),
        ),
    ],
)
def test_each_filter_normalizes_to_an_application_value(parameters, expected):
    assert parse(**parameters).query.filters == expected


def test_a_half_open_range_accepts_adjacent_windows():
    filters = parse(
        started_from="2026-10-01T09:07:04Z", started_before="2026-10-01T10:07:04Z"
    ).query.filters
    assert (filters.started_from, filters.started_before) == (TIMESTAMP, LATER)


@pytest.mark.parametrize(
    "parameters",
    [
        {"status": "in_progress"},
        {"status": "COMPLETE"},
        {"status": ""},
        {"started_from": "2026-10-01"},
        {"started_from": "2026-10-01T09:07:04"},
        {"started_from": "1759309624"},
        {"started_before": "not-a-timestamp"},
        {"boundary": ""},
        {"boundary": "pay\x00ments"},
        {"boundary": "a" * (MAX_FILTER_TEXT_LENGTH + 1)},
        {"invoked_by_email": ""},
        {"invoked_by_email": "ops\x00@example.invalid"},
        {"page_size": "0"},
        {"page_size": "101"},
        {"page_size": "-1"},
        {"page_size": " 25"},
        {"page_size": "25.0"},
        {"page_size": "2_5"},
        {"page_size": "+25"},
        {"page_size": ""},
        {"page_size": "all"},
        # Equal bounds select nothing under a half-open range.
        {"started_from": "2026-10-01T09:07:04Z", "started_before": "2026-10-01T09:07:04Z"},
        {"started_from": "2026-10-01T10:07:04Z", "started_before": "2026-10-01T09:07:04Z"},
        {"limit": "25"},
        {"offset": "0"},
        {"sort": "started_at"},
        {"boundary_contains": "payments"},
        {"STATUS": "COMPLETED"},
    ],
)
def test_invalid_and_unknown_parameters_are_rejected(parameters):
    with pytest.raises(ApplicationError) as caught:
        parse(**parameters)
    assert caught.value.code == ErrorCode.INVALID_FIELD


@pytest.mark.parametrize("value", ["1", "25", "100"])
def test_page_size_accepts_its_documented_range(value):
    assert parse(page_size=value).query.page_size == int(value)
    assert MAX_PAGE_SIZE == 100


@pytest.mark.parametrize("name", sorted({"status", "page_size", "cursor", "boundary"}))
def test_repeated_scalar_parameters_are_rejected(name):
    with pytest.raises(ApplicationError) as caught:
        parse_session_list_request([(name, "COMPLETED"), (name, "FAILED")])
    assert caught.value.code == ErrorCode.INVALID_FIELD


def test_repeated_fields_remain_the_only_multivalued_parameter():
    request = parse_session_list_request(
        [("fields", "started_at"), ("fields", "metadata.boundary")]
    )
    assert request.query.fields == ("metadata.boundary", "session_id", "started_at")
    assert request.projected is True


@pytest.mark.parametrize("value", [None, 25, b"25"])
def test_non_string_parameter_values_are_rejected(value):
    with pytest.raises(ApplicationError) as caught:
        parse_session_list_request([("page_size", value)])
    assert caught.value.code == ErrorCode.INVALID_FIELD


def test_cursors_are_offered_only_for_reachable_directions():
    terminal = cursors([], anchored_page())
    assert (terminal.next_cursor, terminal.previous_cursor) == (None, None)

    both = cursors([], anchored_page(has_newer=True, has_older=True))
    assert isinstance(both.next_cursor, str) and isinstance(both.previous_cursor, str)
    assert both.next_cursor != both.previous_cursor


def test_an_empty_page_navigates_nowhere():
    result = cursors([], SessionPage(items=[], total_count=9))
    assert (result.items, result.total_count) == ([], 9)
    assert (result.next_cursor, result.previous_cursor) == (None, None)


@pytest.mark.parametrize("direction", ["next", "previous"])
def test_a_minted_cursor_round_trips_to_its_anchor(direction):
    parameters = [("status", "COMPLETED"), ("page_size", "10")]
    older = PageAnchor(started_at=TIMESTAMP, session_id=SESSION_ID)
    newer = PageAnchor(started_at=LATER, session_id=OTHER_ID)
    result = cursors(
        parameters,
        anchored_page(newest=newer, oldest=older, total_count=4, has_newer=True, has_older=True),
    )
    cursor = result.next_cursor if direction == "next" else result.previous_cursor
    anchor = older if direction == "next" else newer

    position = parse_session_list_request(
        [*parameters, ("cursor", cursor)]
    ).query.position
    assert position == PagePosition(
        started_at=anchor.started_at, session_id=anchor.session_id, direction=direction
    )


def test_a_cursor_survives_a_changed_field_selection():
    parameters = [("boundary", "payments")]
    cursor = cursors(parameters, anchored_page(has_older=True)).next_cursor
    position = parse_session_list_request(
        [*parameters, ("cursor", cursor), ("fields", "metadata")]
    ).query.position
    assert position.session_id == SESSION_ID


@pytest.mark.parametrize(
    "changed",
    [
        [],
        [("status", "FAILED")],
        [("status", "COMPLETED"), ("page_size", "11")],
        [("status", "COMPLETED"), ("boundary", "payments")],
        [("status", "COMPLETED"), ("started_from", "2026-10-01T09:07:04Z")],
    ],
)
def test_a_cursor_cannot_be_reused_with_different_filters(changed):
    original = [("status", "COMPLETED"), ("page_size", "10")]
    cursor = cursors(original, anchored_page(has_older=True)).next_cursor
    with pytest.raises(ApplicationError) as caught:
        parse_session_list_request([*changed, ("cursor", cursor)])
    assert caught.value.code == ErrorCode.INVALID_FIELD


def minted() -> str:
    return cursors([], anchored_page(has_older=True)).next_cursor



def reencode(replace: str, with_value: str) -> str:
    cursor = minted()
    raw = urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)).decode("ascii")
    return urlsafe_b64encode(
        raw.replace(replace, with_value).encode("ascii")
    ).decode("ascii").rstrip("=")


@pytest.mark.parametrize(
    "cursor",
    [
        "",
        "not-base64-$",
        "!!!!",
        "a",
        "YQ",
        urlsafe_b64encode(b"v1|next|0|" + SESSION_ID.encode()).decode().rstrip("="),
        urlsafe_b64encode(b"v1|next|0|" + SESSION_ID.encode() + b"|x|y").decode().rstrip("="),
        urlsafe_b64encode(b"\xff\xfe").decode().rstrip("="),
        "A" * 513,
    ],
)
def test_malformed_cursors_are_rejected(cursor):
    with pytest.raises(ApplicationError) as caught:
        parse(cursor=cursor)
    assert caught.value.code == ErrorCode.INVALID_FIELD


@pytest.mark.parametrize(
    ("replace", "with_value"),
    [
        ("v1", "v2"),
        ("next", "forward"),
        ("next", "NEXT"),
        (SESSION_ID, SESSION_ID.upper()),
        (SESSION_ID, "not-an-object-id-value00"),
        (SESSION_ID, "68df8b00aef4d8537282f0"),
    ],
)
def test_tampered_cursor_components_are_rejected(replace, with_value):
    with pytest.raises(ApplicationError) as caught:
        parse(cursor=reencode(replace, with_value))
    assert caught.value.code == ErrorCode.INVALID_FIELD


def test_a_tampered_fingerprint_is_rejected():
    cursor = minted()
    raw = urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)).decode("ascii")
    parts = raw.split("|")
    parts[4] = "0" * len(parts[4])
    tampered = urlsafe_b64encode("|".join(parts).encode("ascii")).decode().rstrip("=")
    with pytest.raises(ApplicationError) as caught:
        parse(cursor=tampered)
    assert caught.value.code == ErrorCode.INVALID_FIELD


@pytest.mark.parametrize("milliseconds", ["999999999999999999", "-999999999999999999"])
def test_an_unrepresentable_cursor_timestamp_is_rejected(milliseconds):
    cursor = minted()
    raw = urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)).decode("ascii")
    parts = raw.split("|")
    parts[2] = milliseconds
    unrepresentable = urlsafe_b64encode("|".join(parts).encode("ascii")).decode().rstrip("=")
    with pytest.raises(ApplicationError) as caught:
        parse(cursor=unrepresentable)
    assert caught.value.code == ErrorCode.INVALID_FIELD


def test_pre_epoch_anchors_round_trip():
    anchor = PageAnchor(
        started_at=datetime(1969, 7, 20, 20, 17, 40, tzinfo=timezone.utc),
        session_id=SESSION_ID,
    )
    cursor = cursors([], anchored_page(newest=anchor, oldest=anchor, has_older=True)).next_cursor
    assert parse(cursor=cursor).query.position.started_at == anchor.started_at


def test_service_rejects_an_invalid_parameter_before_any_repository_call():
    sessions = AsyncMock(spec=SessionRepository)
    runs = AsyncMock(spec=RunRepository)
    service = SessionService(sessions, runs)
    with pytest.raises(ApplicationError) as caught:
        asyncio.run(service.list_sessions([("page_size", "1000")]))
    assert caught.value.code == ErrorCode.INVALID_FIELD
    assert sessions.mock_calls == []
    assert runs.mock_calls == []


def test_filters_and_page_size_reach_the_repository(api_client):
    client, sessions, runs = api_client
    sessions.list_page.return_value = session_page({"session_id": SESSION_ID})
    response = client.get("/v1/sessions", params={
        "fields": "session_id",
        "status": "FAILED",
        "started_from": "2026-10-01T09:07:04Z",
        "started_before": "2026-10-01T10:07:04Z",
        "boundary": "payments",
        "invoked_by_email": "ops@example.invalid",
        "page_size": "5",
    })
    assert response.status_code == 200
    assert response.json() == page_response([{"session_id": SESSION_ID}], page_size=5)
    query = sessions.list_page.await_args.args[0]
    assert query.page_size == 5
    assert query.fields == ("session_id",)
    assert query.position is None
    assert query.filters == SessionFilters(
        status="FAILED",
        started_from=TIMESTAMP,
        started_before=LATER,
        boundary_contains="payments",
        invoked_by_email="ops@example.invalid",
    )
    assert runs.mock_calls == []


@pytest.mark.parametrize(
    "params",
    [
        {"status": "closed"},
        {"page_size": "0"},
        {"page_size": "101"},
        {"started_from": "2026-10-01"},
        {"boundary": ""},
        {"cursor": "tampered"},
        {"limit": "10"},
        {"offset": "10"},
    ],
)
def test_invalid_list_parameters_are_rejected_before_repository_access(api_client, params):
    client, sessions, runs = api_client
    response = client.get("/v1/sessions", params=params)
    assert response.status_code == 400
    assert response.json() == INVALID_FIELD
    assert sessions.mock_calls == []
    assert runs.mock_calls == []


def test_advertised_cursor_is_accepted_on_the_next_request(api_client):
    client, sessions, _ = api_client
    sessions.list_page.return_value = session_page(
        {"session_id": SESSION_ID}, total_count=4, has_older=True
    )
    first = client.get("/v1/sessions", params={"fields": "session_id", "status": "COMPLETED"})
    assert first.status_code == 200
    cursor = first.json()["next_cursor"]
    assert isinstance(cursor, str)
    assert first.json()["previous_cursor"] is None

    second = client.get("/v1/sessions", params={
        "fields": "session_id", "status": "COMPLETED", "cursor": cursor,
    })
    assert second.status_code == 200
    position = sessions.list_page.await_args.args[0].position
    assert position.direction == "next"
    assert position.session_id == SESSION_ID


def test_a_cursor_from_different_filters_is_rejected(api_client):
    client, sessions, _ = api_client
    sessions.list_page.return_value = session_page(
        {"session_id": SESSION_ID}, total_count=4, has_older=True
    )
    first = client.get("/v1/sessions", params={"fields": "session_id", "status": "COMPLETED"})
    cursor = first.json()["next_cursor"]
    sessions.reset_mock()

    response = client.get("/v1/sessions", params={
        "fields": "session_id", "status": "FAILED", "cursor": cursor,
    })
    assert response.status_code == 400
    assert response.json() == INVALID_FIELD
    assert sessions.mock_calls == []
