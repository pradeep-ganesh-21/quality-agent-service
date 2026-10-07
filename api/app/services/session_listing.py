"""Validation, paging, and cursor rules for the session list endpoint.

Cursors are opaque continuation values, not credentials. They carry no secret
and are not signed; the embedded fingerprint only detects reuse against a
different filter set or page size.
"""

import hashlib
import json
import re
from base64 import urlsafe_b64decode, urlsafe_b64encode
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from hmac import compare_digest
from typing import cast

from app.domain import SessionStatus
from app.errors import ApplicationError, ErrorCode
from app.repositories.protocols import (
    PageAnchor,
    PageDirection,
    PagePosition,
    SessionFilters,
    SessionListQuery,
    SessionPage,
    SessionRecord,
)
from app.services.mapping import normalize_session_fields, parse_timestamp, validate_utf8

DEFAULT_PAGE_SIZE = 25
MAX_PAGE_SIZE = 100
# Filter text is bounded so an oversized value fails as a request error instead
# of a database expression limit. Stored documents keep their unbounded contract.
MAX_FILTER_TEXT_LENGTH = 256

FIELDS_PARAMETER = "fields"
SCALAR_LIST_PARAMETERS = frozenset(
    {
        "status",
        "started_from",
        "started_before",
        "boundary",
        "invoked_by_email",
        "page_size",
        "cursor",
    }
)
LIST_PARAMETERS = SCALAR_LIST_PARAMETERS | {FIELDS_PARAMETER}

_SESSION_STATUS_VALUES = frozenset(status.value for status in SessionStatus)
_CURSOR_VERSION = "v1"
_CURSOR_DIRECTIONS = ("next", "previous")
_CURSOR_SEPARATOR = "|"
_CURSOR_TEXT = re.compile(r"[A-Za-z0-9_-]{1,512}")
_PAGE_SIZE_TEXT = re.compile(r"0|[1-9][0-9]{0,2}")
_MILLISECONDS_TEXT = re.compile(r"-?(?:0|[1-9][0-9]{0,17})")
_SESSION_ID_TEXT = re.compile(r"[0-9a-f]{24}")
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
_MILLISECOND = timedelta(milliseconds=1)


@dataclass(frozen=True, slots=True)
class SessionListRequest:
    query: SessionListQuery
    # Selection changes response validation but not membership or ordering.
    projected: bool
    fingerprint: str


@dataclass(frozen=True, slots=True)
class SessionListResult:
    items: list[SessionRecord]
    page_size: int
    total_count: int
    next_cursor: str | None
    previous_cursor: str | None
    projected: bool


def parse_session_list_request(
    parameters: Sequence[tuple[str, str]] | None = None,
) -> SessionListRequest:
    """Validate raw list query parameters into a repository query."""
    selectors: list[str] | None = None
    scalars: dict[str, str] = {}
    for name, value in parameters or ():
        if not isinstance(name, str) or not isinstance(value, str):
            raise ApplicationError(ErrorCode.INVALID_FIELD)
        if name == FIELDS_PARAMETER:
            if selectors is None:
                selectors = []
            selectors.append(value)
            continue
        # Unknown and repeated parameters are rejected rather than ignored, so a
        # misspelled filter cannot silently widen a result page.
        if name not in SCALAR_LIST_PARAMETERS or name in scalars:
            raise ApplicationError(ErrorCode.INVALID_FIELD)
        scalars[name] = value

    fields = normalize_session_fields(selectors)
    page_size = _page_size(scalars.get("page_size"))
    filters = _filters(scalars)
    fingerprint = _fingerprint(filters, page_size)
    position = _position(scalars.get("cursor"), fingerprint)
    return SessionListRequest(
        query=SessionListQuery(
            fields=fields,
            page_size=page_size,
            filters=filters,
            position=position,
        ),
        projected=selectors is not None,
        fingerprint=fingerprint,
    )


def build_session_list_result(
    request: SessionListRequest, page: SessionPage
) -> SessionListResult:
    """Attach navigation cursors to a retrieved page.

    A cursor is offered only for a direction the repository reported as
    reachable, so an exhausted or stale page navigates nowhere.
    """
    return SessionListResult(
        items=page.items,
        page_size=request.query.page_size,
        total_count=page.total_count,
        next_cursor=(
            _cursor(page.oldest, "next", request.fingerprint) if page.has_older else None
        ),
        previous_cursor=(
            _cursor(page.newest, "previous", request.fingerprint)
            if page.has_newer
            else None
        ),
        projected=request.projected,
    )


def _page_size(value: str | None) -> int:
    if value is None:
        return DEFAULT_PAGE_SIZE
    # Strict digits only: Python would otherwise accept padding, signs, and
    # underscore separators such as "2_5".
    if _PAGE_SIZE_TEXT.fullmatch(value) is None:
        raise ApplicationError(ErrorCode.INVALID_FIELD)
    page_size = int(value)
    if not 1 <= page_size <= MAX_PAGE_SIZE:
        raise ApplicationError(ErrorCode.INVALID_FIELD)
    return page_size


def _filters(scalars: dict[str, str]) -> SessionFilters:
    started_from = _timestamp(scalars.get("started_from"))
    started_before = _timestamp(scalars.get("started_before"))
    # The range is start-inclusive and end-exclusive, so equal bounds select
    # nothing and are treated as a request mistake.
    if (
        started_from is not None
        and started_before is not None
        and started_from >= started_before
    ):
        raise ApplicationError(ErrorCode.INVALID_FIELD)
    return SessionFilters(
        status=_status(scalars.get("status")),
        started_from=started_from,
        started_before=started_before,
        boundary_contains=_filter_text(scalars.get("boundary")),
        invoked_by_email=_filter_text(scalars.get("invoked_by_email")),
    )


def _status(value: str | None) -> str | None:
    if value is None:
        return None
    if value not in _SESSION_STATUS_VALUES:
        raise ApplicationError(ErrorCode.INVALID_FIELD)
    return value


def _timestamp(value: str | None) -> datetime | None:
    if value is None:
        return None
    try:
        return parse_timestamp(value)
    except ValueError:
        # The supplied value is never echoed back to the client.
        raise ApplicationError(ErrorCode.INVALID_FIELD) from None


def _filter_text(value: str | None) -> str | None:
    if value is None:
        return None
    if not value or len(value) > MAX_FILTER_TEXT_LENGTH or "\x00" in value:
        raise ApplicationError(ErrorCode.INVALID_FIELD)
    validate_utf8(value)
    return value


def _fingerprint(filters: SessionFilters, page_size: int) -> str:
    """Bind a cursor to the filters and page size that produced it."""
    payload = json.dumps(
        [
            _CURSOR_VERSION,
            page_size,
            filters.status,
            _isoformat(filters.started_from),
            _isoformat(filters.started_before),
            filters.boundary_contains,
            filters.invoked_by_email,
        ],
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _isoformat(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat()


def _cursor(
    anchor: PageAnchor | None, direction: PageDirection, fingerprint: str
) -> str | None:
    if anchor is None:
        return None
    milliseconds = (anchor.started_at - _EPOCH) // _MILLISECOND
    raw = _CURSOR_SEPARATOR.join(
        (
            _CURSOR_VERSION,
            direction,
            str(milliseconds),
            anchor.session_id,
            fingerprint,
        )
    )
    return urlsafe_b64encode(raw.encode("ascii")).decode("ascii").rstrip("=")


def _position(value: str | None, fingerprint: str) -> PagePosition | None:
    if value is None:
        return None
    # Validate the alphabet first: base64 decoding otherwise discards characters
    # outside it and would accept a corrupted cursor.
    if _CURSOR_TEXT.fullmatch(value) is None:
        raise ApplicationError(ErrorCode.INVALID_FIELD)
    try:
        raw = urlsafe_b64decode(value + "=" * (-len(value) % 4)).decode("ascii")
    except (ValueError, UnicodeDecodeError):
        raise ApplicationError(ErrorCode.INVALID_FIELD) from None

    parts = raw.split(_CURSOR_SEPARATOR)
    if len(parts) != 5:
        raise ApplicationError(ErrorCode.INVALID_FIELD)
    version, direction, milliseconds, session_id, mark = parts
    if (
        version != _CURSOR_VERSION
        or direction not in _CURSOR_DIRECTIONS
        or _MILLISECONDS_TEXT.fullmatch(milliseconds) is None
        or _SESSION_ID_TEXT.fullmatch(session_id) is None
        or not compare_digest(mark, fingerprint)
    ):
        raise ApplicationError(ErrorCode.INVALID_FIELD)
    try:
        started_at = _EPOCH + int(milliseconds) * _MILLISECOND
    except (OverflowError, ValueError):
        raise ApplicationError(ErrorCode.INVALID_FIELD) from None
    return PagePosition(
        started_at=started_at,
        session_id=session_id,
        direction=cast(PageDirection, direction),
    )
