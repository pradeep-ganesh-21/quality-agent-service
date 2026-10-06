from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI

from app.config import Settings
from app.errors import register_exception_handlers
from app.routes import router


def create_app(settings: Settings | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        configuration = settings if settings is not None else Settings()
        timeout = httpx.Timeout(
            connect=configuration.httpx_connect_timeout_seconds,
            read=configuration.httpx_read_timeout_seconds,
            write=configuration.httpx_write_timeout_seconds,
            pool=configuration.httpx_pool_timeout_seconds,
        )
        async with httpx.AsyncClient(
            base_url=configuration.api_base_url, timeout=timeout
        ) as client:
            app.state.api_client = client
            yield

    app = FastAPI(
        lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None
    )
    register_exception_handlers(app)
    app.include_router(router)
    return app
