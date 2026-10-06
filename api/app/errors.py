from enum import StrEnum


class ErrorCode(StrEnum):
    INVALID_JSON = "invalid_json"
    INVALID_BODY = "invalid_body"
    FORBIDDEN_FIELD = "forbidden_field"
    MISSING_FIELD = "missing_field"
    INVALID_FIELD = "invalid_field"
    INVALID_KEY = "invalid_key"
    PAYLOAD_TOO_DEEP = "payload_too_deep"
    NON_FINITE_NUMBER = "non_finite_number"
    VALUE_OUT_OF_RANGE = "value_out_of_range"
    ROUTE_NOT_FOUND = "route_not_found"
    SESSION_NOT_FOUND = "session_not_found"
    SESSION_NOT_OPEN = "session_not_open"
    METHOD_NOT_ALLOWED = "method_not_allowed"
    DOCUMENT_TOO_LARGE = "document_too_large"
    UNSUPPORTED_MEDIA_TYPE = "unsupported_media_type"
    INTERNAL_ERROR = "internal_error"


class ApplicationError(Exception):
    def __init__(self, code: ErrorCode) -> None:
        self.code = code
        super().__init__(code.value)
