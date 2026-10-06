from collections.abc import Mapping
from typing import Any, Protocol


class SessionRepository(Protocol):
    async def create(self, values: Mapping[str, Any]) -> str: ...
