from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException
from starlette.staticfiles import StaticFiles


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(HTTPException)
    async def http_error(request: Request, error: HTTPException) -> JSONResponse:
        code, message = {
            404: ("route_not_found", "Route not found."),
            405: ("method_not_allowed", "Method not allowed."),
        }.get(error.status_code, ("http_error", "Request could not be completed."))
        headers = error.headers
        if (
            error.status_code == 405
            and headers is None
            and isinstance(request.scope.get("endpoint"), StaticFiles)
        ):
            headers = {"Allow": "GET, HEAD"}
        return JSONResponse(
            status_code=error.status_code,
            content={"error": {"code": code, "message": message}},
            headers=headers,
        )
