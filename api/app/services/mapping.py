import json
import math
import re
from datetime import datetime, timezone
from typing import Any

from app.errors import ApplicationError, ErrorCode

SESSION_CREATE_RESERVED_FIELDS = frozenset(
    {
        "_id",
        "session_id",
        "received_at",
        "schema_version",
        "status",
        "completion_time",
        "last_step_executed",
        "execution_outcome",
    }
)
SESSION_CREATE_CONSUMED_FIELDS = frozenset({"started_at"})
SESSION_PATCH_RESERVED_FIELDS = frozenset(
    {"_id", "session_id", "received_at", "schema_version"}
)
SESSION_PATCH_CONSUMED_FIELDS = frozenset(
    {
        "started_at",
        "status",
        "completion_time",
        "last_step_executed",
        "execution_outcome",
    }
)
EXECUTION_OUTCOME_COUNT_FIELDS = (
    "defect_count",
    "gap_count",
    "contract_ingredient_count",
)

_RFC3339 = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}[Tt]"
    r"(?:[01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9]"
    r"(?:\.[0-9]+)?"
    r"(?:[Zz]|[+-](?:[01][0-9]|2[0-3]):[0-5][0-9])"
)


def _reject_non_finite_constant(value: str) -> None:
    raise ApplicationError(ErrorCode.NON_FINITE_NUMBER)


def parse_json_object(body: bytes) -> dict[str, Any]:
    try:
        value = json.loads(body, parse_constant=_reject_non_finite_constant)
    except (json.JSONDecodeError, UnicodeDecodeError, RecursionError):
        raise ApplicationError(ErrorCode.INVALID_JSON) from None
    except ValueError:
        # Python's integer digit limit can reject values before the range walk.
        raise ApplicationError(ErrorCode.VALUE_OUT_OF_RANGE) from None
    if not isinstance(value, dict):
        raise ApplicationError(ErrorCode.INVALID_BODY)
    return value


def validate_json_values(body: dict[str, Any]) -> None:
    pending: list[Any] = [body]
    while pending:
        value = pending.pop()
        if isinstance(value, dict):
            for key, child in value.items():
                if "\x00" in key:
                    raise ApplicationError(ErrorCode.INVALID_KEY)
                _validate_utf8(key)
                pending.append(child)
        elif isinstance(value, list):
            pending.extend(value)
        elif isinstance(value, str):
            _validate_utf8(value)
        elif isinstance(value, int) and not isinstance(value, bool):
            if not -(2**63) <= value < 2**63:
                raise ApplicationError(ErrorCode.VALUE_OUT_OF_RANGE)
        elif isinstance(value, float) and not math.isfinite(value):
            raise ApplicationError(ErrorCode.NON_FINITE_NUMBER)


def _validate_utf8(value: str) -> None:
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        raise ApplicationError(ErrorCode.INVALID_FIELD) from None


def validate_document_depth(document: dict[str, Any]) -> None:
    pending: list[tuple[Any, int]] = [(document, 1)]
    while pending:
        value, depth = pending.pop()
        if not isinstance(value, (dict, list)):
            continue
        if depth > 100:
            raise ApplicationError(ErrorCode.PAYLOAD_TOO_DEEP)
        children = value.values() if isinstance(value, dict) else value
        pending.extend((child, depth + 1) for child in children)


def utc_milliseconds(value: datetime) -> datetime:
    value = value.astimezone(timezone.utc)
    return value.replace(microsecond=(value.microsecond // 1000) * 1000)


def format_timestamp(value: datetime) -> str:
    return utc_milliseconds(value).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def parse_timestamp(value: Any) -> datetime:
    if not isinstance(value, str) or _RFC3339.fullmatch(value) is None:
        raise ValueError("Timestamp must be an offset-aware RFC 3339 string.")
    try:
        return utc_milliseconds(datetime.fromisoformat(value.upper()))
    except (ValueError, OverflowError):
        raise ValueError("Timestamp must be a representable RFC 3339 value.") from None


def validate_execution_outcome(value: dict[str, Any] | None) -> dict[str, Any] | None:
    if value is None:
        return None
    for field in EXECUTION_OUTCOME_COUNT_FIELDS:
        if field not in value:
            continue
        count = value[field]
        if type(count) is not int or not 0 <= count < 2**63:
            raise ValueError("Supplied counts must be nonnegative signed 64-bit integers.")
    return value
