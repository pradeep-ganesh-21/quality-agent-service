from typing import Annotated

from fastapi import APIRouter, Depends, Request, status

from app.dependencies import get_session_service
from app.errors import ApplicationError, ErrorCode
from app.schemas.sessions import SessionCreatedResponse
from app.services.mapping import parse_json_object
from app.services.session_service import SessionService

router = APIRouter(prefix="/v1/sessions", tags=["sessions"])


@router.post("", status_code=status.HTTP_201_CREATED, response_model=SessionCreatedResponse)
async def create_session(
    request: Request,
    service: Annotated[SessionService, Depends(get_session_service)],
) -> SessionCreatedResponse:
    media_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if media_type != "application/json":
        raise ApplicationError(ErrorCode.UNSUPPORTED_MEDIA_TYPE)
    body = parse_json_object(await request.body())
    session_id = await service.create_session(body)
    return SessionCreatedResponse(session_id=session_id)
