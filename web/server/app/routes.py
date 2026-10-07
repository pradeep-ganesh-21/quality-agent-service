from pathlib import Path

from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.responses import FileResponse
from starlette.staticfiles import StaticFiles

router = APIRouter()


@router.get("/healthz")
async def health() -> dict[str, str]:
    return {"status": "ok"}


def register_static_routes(app: FastAPI, static_root: Path) -> None:
    assets_root = static_root / "assets"
    if assets_root.is_dir() and assets_root.resolve().is_relative_to(static_root):
        app.mount(
            "/assets",
            StaticFiles(directory=assets_root, html=False, follow_symlink=False),
            name="assets",
        )

    ui_router = APIRouter()

    @ui_router.get("/")
    @ui_router.get("/sessions/{session_id}")
    def index() -> FileResponse:
        index_path = (static_root / "index.html").resolve()
        if not index_path.is_relative_to(static_root) or not index_path.is_file():
            raise HTTPException(status_code=404)
        return FileResponse(
            index_path, media_type="text/html", headers={"Cache-Control": "no-cache"}
        )

    app.include_router(ui_router)
