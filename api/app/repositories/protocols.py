from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal, Protocol, TypeAlias

SessionRecord: TypeAlias = dict[str, Any]
RunRecord: TypeAlias = dict[str, Any]

# "next" walks toward older sessions; "previous" walks toward newer sessions.
PageDirection: TypeAlias = Literal["next", "previous"]


@dataclass(frozen=True, slots=True)
class SessionFilters:
    """Validated list filters holding plain application values only.

    Text filters are literal values, not patterns. An adapter escapes them
    before building any database expression.
    """

    status: str | None = None
    started_from: datetime | None = None
    started_before: datetime | None = None
    boundary_contains: str | None = None
    invoked_by_email: str | None = None


@dataclass(frozen=True, slots=True)
class PagePosition:
    """An exclusive page boundary expressed in the list sort key."""

    started_at: datetime
    session_id: str
    direction: PageDirection


@dataclass(frozen=True, slots=True)
class SessionListQuery:
    fields: tuple[str, ...]
    page_size: int
    filters: SessionFilters = field(default_factory=SessionFilters)
    position: PagePosition | None = None


@dataclass(frozen=True, slots=True)
class PageAnchor:
    """The sort key of a returned record, used to mint continuation cursors.

    Anchors are reported separately from records because the list sort key is
    not necessarily a selected response field.
    """

    started_at: datetime
    session_id: str


@dataclass(frozen=True, slots=True)
class SessionPage:
    items: list[SessionRecord]
    total_count: int
    newest: PageAnchor | None = None
    oldest: PageAnchor | None = None
    has_newer: bool = False
    has_older: bool = False


class SessionRepository(Protocol):
    async def create(self, values: Mapping[str, Any]) -> str: ...

    async def get(self, session_id: str) -> SessionRecord | None: ...

    async def list_page(self, query: SessionListQuery) -> SessionPage: ...

    async def patch_open_session(
        self,
        session_id: str,
        known: Mapping[str, Any],
        extras: Mapping[str, Any],
    ) -> str: ...


class RunRepository(Protocol):
    async def list_for_session(self, session_id: str) -> list[RunRecord]: ...
