from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from pydantic import ValidationError

from app.domain import SessionStatus
from app.errors import ApplicationError, ErrorCode
from app.repositories.protocols import SessionRepository
from app.schemas.sessions import SessionCreateRequest
from app.services.mapping import (
    SESSION_CREATE_CONSUMED_FIELDS,
    SESSION_CREATE_RESERVED_FIELDS,
    utc_milliseconds,
    validate_document_depth,
    validate_json_values,
)


class SessionService:
    def __init__(self, repository: SessionRepository) -> None:
        self._repository = repository

    async def create_session(self, body: dict[str, Any]) -> str:
        validate_json_values(body)
        if SESSION_CREATE_RESERVED_FIELDS.intersection(body):
            raise ApplicationError(ErrorCode.FORBIDDEN_FIELD)
        try:
            request = SessionCreateRequest.model_validate(body)
        except ValidationError as error:
            first_issue = error.errors(include_input=False, include_context=False)[0]
            code = (
                ErrorCode.MISSING_FIELD
                if first_issue["type"] == "missing"
                else ErrorCode.INVALID_FIELD
            )
            raise ApplicationError(code) from None

        metadata = {
            key: value
            for key, value in body.items()
            if key not in SESSION_CREATE_CONSUMED_FIELDS
        }
        document = {
            "schema_version": 1,
            "started_at": request.started_at,
            "received_at": utc_milliseconds(datetime.now(timezone.utc)),
            "status": SessionStatus.IN_PROGRESS.value,
            "completion_time": None,
            "last_step_executed": [],
            "execution_outcome": None,
            "metadata": metadata,
        }
        validate_document_depth(document)
        # Validate depth before a recursive copy; deeply nested input is rejected.
        document["metadata"] = deepcopy(metadata)
        return await self._repository.create(document)
