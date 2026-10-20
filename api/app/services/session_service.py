from collections.abc import Sequence
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal, TypeAlias

from pydantic import ValidationError

from app.domain import SessionStatus
from app.errors import ApplicationError, ErrorCode
from app.repositories.protocols import RunRepository, SessionRecord, SessionRepository
from app.schemas.sessions import (
    SessionBulkDeleteRequest,
    SessionCreateRequest,
    SessionPatchRequest,
)
from app.services.mapping import (
    SESSION_CREATE_CONSUMED_FIELDS,
    SESSION_CREATE_RESERVED_FIELDS,
    SESSION_PATCH_CONSUMED_FIELDS,
    SESSION_PATCH_RESERVED_FIELDS,
    utc_milliseconds,
    validate_document_depth,
    validate_json_values,
)
from app.services.session_listing import (
    SessionListResult,
    build_session_list_result,
    parse_session_list_request,
)

DeleteOutcome: TypeAlias = Literal["deleted", "already_deleted", "not_found"]


@dataclass(slots=True)
class BulkDeleteResult:
    deleted: list[str] = field(default_factory=list)
    already_deleted: list[str] = field(default_factory=list)
    not_found: list[str] = field(default_factory=list)


class SessionService:
    def __init__(self, repository: SessionRepository, runs: RunRepository) -> None:
        self._repository = repository
        self._runs = runs

    async def list_sessions(
        self, parameters: Sequence[tuple[str, str]] | None = None
    ) -> SessionListResult:
        request = parse_session_list_request(parameters)
        page = await self._repository.list_page(request.query)
        return build_session_list_result(request, page)

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
            "deleted_at": None,
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

    async def delete_session(self, session_id: str) -> None:
        outcome = await self._soft_delete(session_id, _deletion_time())
        if outcome == "not_found":
            raise ApplicationError(ErrorCode.SESSION_NOT_FOUND)
        if outcome == "already_deleted":
            raise ApplicationError(ErrorCode.SESSION_DELETED)

    async def delete_sessions(self, body: dict[str, Any]) -> BulkDeleteResult:
        validate_json_values(body)
        try:
            request = SessionBulkDeleteRequest.model_validate(body)
        except ValidationError as error:
            first_issue = error.errors(include_input=False, include_context=False)[0]
            code = (
                ErrorCode.MISSING_FIELD
                if first_issue["type"] == "missing"
                else ErrorCode.INVALID_FIELD
            )
            raise ApplicationError(code) from None

        deleted_at = _deletion_time()
        result = BulkDeleteResult()
        # Duplicates collapse to their first occurrence; IDs are processed in order.
        for session_id in dict.fromkeys(request.session_ids):
            outcome = await self._soft_delete(session_id, deleted_at)
            getattr(result, outcome).append(session_id)
        return result

    async def _soft_delete(self, session_id: str, deleted_at: datetime) -> DeleteOutcome:
        # The session is stamped before its runs without a transaction. A failure
        # between the two leaves unstamped runs that a repeated delete stamps.
        if await self._repository.soft_delete(session_id, deleted_at):
            await self._runs.soft_delete_for_session(session_id, deleted_at)
            return "deleted"
        state = await self._repository.state(session_id)
        if state is None:
            return "not_found"
        if state.deleted_at is None:
            # The guarded update found no live session, yet the lookup did.
            raise ApplicationError(ErrorCode.INTERNAL_ERROR)
        await self._runs.soft_delete_for_session(session_id, state.deleted_at)
        return "already_deleted"


def _deletion_time() -> datetime:
    return utc_milliseconds(datetime.now(timezone.utc))
