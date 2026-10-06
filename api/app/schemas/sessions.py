from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.services.mapping import parse_timestamp


class SessionCreateRequest(BaseModel):
    model_config = ConfigDict(extra="allow", strict=True, hide_input_in_errors=True)

    started_at: datetime

    @field_validator("started_at", mode="before")
    @classmethod
    def validate_started_at(cls, value: Any) -> datetime:
        return parse_timestamp(value)


class SessionCreatedResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    session_id: str = Field(pattern=r"^[0-9a-f]{24}$")
