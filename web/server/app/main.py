from fastapi import FastAPI

from app.errors import register_exception_handlers
from app.routes import router


def create_app() -> FastAPI:
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    register_exception_handlers(app)
    app.include_router(router)
    return app
