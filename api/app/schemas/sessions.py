from datetime import datetime
from typing import Any, Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
    field_validator,
)

from app.schemas.runs import RunResponse
from app.services.mapping import format_timestamp, parse_timestamp, validate_execution_outcome


class SessionCreateRequest(BaseModel):
    model_config = ConfigDict(extra="allow", strict=True, hide_input_in_errors=True)

    started_at: datetime

    @field_validator("started_at", mode="before")
    @classmethod
    def validate_started_at(cls, value: Any) -> datetime:
        return parse_timestamp(value)


class SessionPatchRequest(BaseModel):
    model_config = ConfigDict(extra="allow", strict=True, hide_input_in_errors=True)

    # Defaults represent omission. Validators still reject explicit null where required.
    started_at: datetime | None = None
    status: Literal["COMPLETED", "FAILED"] | None = None
    completion_time: datetime | None = None
    last_step_executed: list[str] | None = None
    execution_outcome: dict[str, Any] | None = None

    @field_validator("started_at", mode="before")
    @classmethod
    def validate_started_at(cls, value: Any) -> datetime:
        return parse_timestamp(value)

    @field_validator("completion_time", mode="before")
    @classmethod
    def validate_completion_time(cls, value: Any) -> datetime | None:
        return None if value is None else parse_timestamp(value)

    @field_validator("status", "last_step_executed", mode="before")
    @classmethod
    def reject_explicit_null(cls, value: Any) -> Any:
        if value is None:
            raise ValueError("This field must not be null when supplied.")
        return value

    @field_validator("execution_outcome")
    @classmethod
    def validate_outcome(cls, value: dict[str, Any] | None) -> dict[str, Any] | None:
        return validate_execution_outcome(value)


class SessionIdResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    session_id: str = Field(pattern=r"^[0-9a-f]{24}$")


class SessionSummaryResponse(SessionIdResponse):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)

    schema_version: int
    started_at: AwareDatetime
    received_at: AwareDatetime
    status: Literal["IN_PROGRESS", "COMPLETED", "FAILED"]
    completion_time: AwareDatetime | None
    last_step_executed: list[str]
    execution_outcome: dict[str, Any] | None

    @field_serializer("started_at", "received_at", "completion_time", when_used="json")
    def serialize_timestamp(self, value: datetime | None) -> str | None:
        return None if value is None else format_timestamp(value)


class SessionDetailResponse(SessionSummaryResponse):
    metadata: dict[str, Any]
    runs: list[RunResponse]
