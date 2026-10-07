from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, status
from pydantic import ValidationError

from app.dependencies import get_session_service
from app.errors import ApplicationError, ErrorCode
from app.repositories.protocols import SessionRecord
from app.schemas.sessions import (
    SessionDetailResponse,
    SessionIdResponse,
    SessionListResponse,
    SessionProjectionResponse,
    SessionSummaryResponse,
)
from app.services.mapping import parse_json_object
from app.services.session_service import SessionService

router = APIRouter(prefix="/v1/sessions", tags=["sessions"])


@router.get(
    "",
    response_model=SessionListResponse,
    response_model_exclude_unset=True,
)
async def list_sessions(
    request: Request,
    service: Annotated[SessionService, Depends(get_session_service)],
) -> SessionListResponse:
    # Query parameters are validated in the service, including repeated and
    # unknown names, so they are passed through unparsed.
    result = await service.list_sessions(request.query_params.multi_items())
    # An incomplete default summary must not pass via the optional-fields model.
    item_model = SessionProjectionResponse if result.projected else SessionSummaryResponse
    try:
        items = [item_model.model_validate(record) for record in result.items]
    except ValidationError:
        # Do not let stored values or arbitrary keys reach the server error log.
        raise ApplicationError(ErrorCode.INTERNAL_ERROR) from None
    return SessionListResponse(
        items=items,
        page_size=result.page_size,
        total_count=result.total_count,
        next_cursor=result.next_cursor,
        previous_cursor=result.previous_cursor,
    )


@router.get("/{session_id}", response_model=SessionDetailResponse)
async def get_session(
    session_id: str,
    service: Annotated[SessionService, Depends(get_session_service)],
) -> SessionRecord:
    return await service.get_session(session_id)


async def _read_json_body(request: Request) -> dict[str, Any]:
    media_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if media_type != "application/json":
        raise ApplicationError(ErrorCode.UNSUPPORTED_MEDIA_TYPE)
    return parse_json_object(await request.body())


@router.post("", status_code=status.HTTP_201_CREATED, response_model=SessionIdResponse)
async def create_session(
    request: Request,
    service: Annotated[SessionService, Depends(get_session_service)],
) -> SessionIdResponse:
    body = await _read_json_body(request)
    session_id = await service.create_session(body)
    return SessionIdResponse(session_id=session_id)


@router.patch("/{session_id}", response_model=SessionIdResponse)
async def patch_session(
    session_id: str,
    request: Request,
    service: Annotated[SessionService, Depends(get_session_service)],
) -> SessionIdResponse:
    body = await _read_json_body(request)
    updated_id = await service.patch_session(session_id, body)
    return SessionIdResponse(session_id=updated_id)
