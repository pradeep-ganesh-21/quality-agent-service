from fastapi import Request

from app.repositories.protocols import RunRepository, SessionRepository
from app.services.session_service import SessionService


async def get_session_service(request: Request) -> SessionService:
    repository: SessionRepository = request.app.state.session_repository
    runs: RunRepository = request.app.state.run_repository
    return SessionService(repository, runs)
