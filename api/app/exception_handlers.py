from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from app.errors import ApplicationError, ErrorCode

ERROR_RESPONSES = {
    ErrorCode.INVALID_JSON: (400, "Request body is not valid JSON."),
    ErrorCode.INVALID_BODY: (400, "Request body must be a JSON object."),
    ErrorCode.FORBIDDEN_FIELD: (400, "Request contains a reserved top-level field."),
    ErrorCode.MISSING_FIELD: (400, "A required field is missing."),
    ErrorCode.INVALID_FIELD: (400, "A request field is invalid."),
    ErrorCode.INVALID_KEY: (400, "Object keys must not contain NUL."),
    ErrorCode.PAYLOAD_TOO_DEEP: (400, "The stored document would exceed 100 nesting levels."),
    ErrorCode.NON_FINITE_NUMBER: (400, "Numbers must be finite."),
    ErrorCode.VALUE_OUT_OF_RANGE: (400, "An integer is outside the supported range."),
    ErrorCode.ROUTE_NOT_FOUND: (404, "Route not found."),
    ErrorCode.METHOD_NOT_ALLOWED: (405, "Method not allowed."),
    ErrorCode.DOCUMENT_TOO_LARGE: (
        413, "The stored document would exceed the MongoDB size limit."
    ),
    ErrorCode.UNSUPPORTED_MEDIA_TYPE: (415, "Content-Type must be application/json."),
    ErrorCode.INTERNAL_ERROR: (500, "The server could not complete the request."),
}


def error_response(
    code: ErrorCode,
    *,
    status_code: int | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    default_status, message = ERROR_RESPONSES[code]
    return JSONResponse(
        status_code=default_status if status_code is None else status_code,
        content={"error": {"code": code.value, "message": message}},
        headers=headers,
    )


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApplicationError)
    async def application_error(request: Request, error: ApplicationError) -> JSONResponse:
        return error_response(error.code)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, error: RequestValidationError) -> JSONResponse:
        issues = error.errors()
        code = (
            ErrorCode.MISSING_FIELD
            if issues and issues[0]["type"] == "missing"
            else ErrorCode.INVALID_FIELD
        )
        return error_response(code)

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, error: HTTPException) -> JSONResponse:
        code = {
            404: ErrorCode.ROUTE_NOT_FOUND,
            405: ErrorCode.METHOD_NOT_ALLOWED,
            415: ErrorCode.UNSUPPORTED_MEDIA_TYPE,
        }.get(error.status_code, ErrorCode.INTERNAL_ERROR)
        return error_response(
            code,
            status_code=error.status_code,
            headers=error.headers,
        )

    @app.exception_handler(Exception)
    async def unexpected_error(request: Request, error: Exception) -> JSONResponse:
        return error_response(ErrorCode.INTERNAL_ERROR)
