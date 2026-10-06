from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(HTTPException)
    async def http_error(request: Request, error: HTTPException) -> JSONResponse:
        code, message = {
            404: ("route_not_found", "Route not found."),
            405: ("method_not_allowed", "Method not allowed."),
        }.get(error.status_code, ("http_error", "Request could not be completed."))
        return JSONResponse(
            status_code=error.status_code,
            content={"error": {"code": code, "message": message}},
            headers=error.headers,
        )
