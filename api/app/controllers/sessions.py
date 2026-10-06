from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, status

from app.dependencies import get_session_service
from app.errors import ApplicationError, ErrorCode
from app.schemas.sessions import SessionIdResponse
from app.services.mapping import parse_json_object
from app.services.session_service import SessionService

router = APIRouter(prefix="/v1/sessions", tags=["sessions"])


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
