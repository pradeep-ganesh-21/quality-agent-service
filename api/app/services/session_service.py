from collections.abc import Sequence
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from pydantic import ValidationError

from app.domain import SessionStatus
from app.errors import ApplicationError, ErrorCode
from app.repositories.protocols import RunRepository, SessionRecord, SessionRepository
from app.schemas.sessions import SessionCreateRequest, SessionPatchRequest
from app.services.mapping import (
    SESSION_CREATE_CONSUMED_FIELDS,
    SESSION_CREATE_RESERVED_FIELDS,
    SESSION_PATCH_CONSUMED_FIELDS,
    SESSION_PATCH_RESERVED_FIELDS,
    normalize_session_fields,
    utc_milliseconds,
    validate_document_depth,
    validate_json_values,
)


class SessionService:
    def __init__(self, repository: SessionRepository, runs: RunRepository) -> None:
        self._repository = repository
        self._runs = runs

    async def list_sessions(self, fields: Sequence[str] | None = None) -> list[SessionRecord]:
        return await self._repository.list_all(normalize_session_fields(fields))

    async def get_session(self, session_id: str) -> SessionRecord:
        session = await self._repository.get(session_id)
        if session is None:
            raise ApplicationError(ErrorCode.SESSION_NOT_FOUND)
        runs = await self._runs.list_for_session(session["session_id"])
        return {**session, "runs": runs}

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

    async def patch_session(self, session_id: str, body: dict[str, Any]) -> str:
        validate_json_values(body)
        if SESSION_PATCH_RESERVED_FIELDS.intersection(body):
            raise ApplicationError(ErrorCode.FORBIDDEN_FIELD)
        try:
            request = SessionPatchRequest.model_validate(body)
        except ValidationError:
            raise ApplicationError(ErrorCode.INVALID_FIELD) from None

        known_input = {
            key: value
            for key, value in body.items()
            if key in SESSION_PATCH_CONSUMED_FIELDS
        }
        extras = {
            key: value
            for key, value in body.items()
            if key not in SESSION_PATCH_CONSUMED_FIELDS
        }
        # Shallow replacement cannot deepen retained data; check incoming values
        # at their stored positions before copying or serializing nested values.
        validate_document_depth({**known_input, "metadata": extras})
        known = request.model_dump(
            mode="python",
            exclude_unset=True,
            include=set(SESSION_PATCH_CONSUMED_FIELDS),
        )
        return await self._repository.patch_open_session(
            session_id, known, deepcopy(extras)
        )
