from pathlib import Path

from fastapi import FastAPI

from app.errors import register_exception_handlers
from app.routes import register_static_routes, router


def create_app(static_root: Path | None = None) -> FastAPI:
    if static_root is None:
        static_root = Path(__file__).parent.parent / "static"
    static_root = static_root.resolve()
    app = FastAPI(
        docs_url=None, redoc_url=None, openapi_url=None, redirect_slashes=False
    )
    register_exception_handlers(app)
    app.include_router(router)
    register_static_routes(app, static_root)
    return app
