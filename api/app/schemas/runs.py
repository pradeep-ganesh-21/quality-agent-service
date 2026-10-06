from datetime import datetime
from typing import Any

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_serializer

from app.services.mapping import format_timestamp


class RunResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)

    run_id: str = Field(pattern=r"^[0-9a-f]{24}$")
    session_id: str = Field(pattern=r"^[0-9a-f]{24}$")
    schema_version: int
    step: str
    command: str
    verdict: str
    occurred_at: AwareDatetime
    received_at: AwareDatetime
    details: dict[str, Any]

    @field_serializer("occurred_at", "received_at", when_used="json")
    def serialize_timestamp(self, value: datetime) -> str:
        return format_timestamp(value)
