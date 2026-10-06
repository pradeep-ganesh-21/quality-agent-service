from collections.abc import Mapping
from typing import Any, Protocol


class SessionRepository(Protocol):
    async def create(self, values: Mapping[str, Any]) -> str: ...

    async def patch_open_session(
        self,
        session_id: str,
        known: Mapping[str, Any],
        extras: Mapping[str, Any],
    ) -> str: ...
