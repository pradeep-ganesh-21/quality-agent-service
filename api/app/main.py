from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import Settings
from app.controllers.health import router as health_router
from app.exception_handlers import register_exception_handlers
from app.repositories.mongo_runtime import mongo_runtime


def create_app(settings: Settings | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        configuration = settings if settings is not None else Settings()
        async with mongo_runtime(
            configuration.mongo_uri.get_secret_value(), configuration.mongo_db_name
        ):
            yield

    app = FastAPI(
        lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None
    )
    register_exception_handlers(app)
    app.include_router(health_router)
    return app
