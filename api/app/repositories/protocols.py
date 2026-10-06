from collections.abc import Mapping
from typing import Any, Protocol, TypeAlias

SessionRecord: TypeAlias = dict[str, Any]
RunRecord: TypeAlias = dict[str, Any]


class SessionRepository(Protocol):
    async def create(self, values: Mapping[str, Any]) -> str: ...

    async def get(self, session_id: str) -> SessionRecord | None: ...

    async def list_all(self) -> list[SessionRecord]: ...

    async def patch_open_session(
        self,
        session_id: str,
        known: Mapping[str, Any],
        extras: Mapping[str, Any],
    ) -> str: ...


class RunRepository(Protocol):
    async def list_for_session(self, session_id: str) -> list[RunRecord]: ...
