"""Pure parsing, value, timestamp, and nesting-depth validation for write payloads."""

from datetime import datetime, timezone

import pytest

from app.errors import ApplicationError, ErrorCode
from app.services import mapping
from app.services.mapping import (
    parse_json_object,
    parse_timestamp,
    validate_document_depth,
    validate_execution_outcome,
    validate_json_values,
)


def nested(levels: int, container: str = "object"):
    """Return a value containing exactly `levels` containers around a scalar leaf."""
    value: object = 0
    for level in range(levels):
        use_object = container == "object" or (container == "mixed" and level % 2 == 0)
        value = {"k": value} if use_object else [value]
    return value


def raises(code: ErrorCode, call, *args):
    with pytest.raises(ApplicationError) as caught:
        call(*args)
    assert caught.value.code == code
    return caught.value


@pytest.mark.parametrize(
    "body",
    [b"", b"   ", b"{", b"{'single': 'quotes'}", b'{"unterminated": "', b"\xff\xfe",
     b'{"trailing": 1,}', b"{} {}", b'{"a": undefined}'],
)
def test_malformed_or_empty_bodies_are_invalid_json(body):
    raises(ErrorCode.INVALID_JSON, parse_json_object, body)


@pytest.mark.parametrize("body", [b"[]", b'[{"started_at": "x"}]', b"null", b"1", b'"text"', b"true"])
def test_non_object_roots_are_invalid_body(body):
    raises(ErrorCode.INVALID_BODY, parse_json_object, body)


@pytest.mark.parametrize("literal", [b"NaN", b"Infinity", b"-Infinity"])
def test_named_non_finite_constants_are_rejected_during_parsing(literal):
    raises(ErrorCode.NON_FINITE_NUMBER, parse_json_object, b'{"value": ' + literal + b"}")


def test_parser_recursion_failure_maps_to_invalid_json(monkeypatch):
    def overflow(*args, **kwargs):
        raise RecursionError("maximum recursion depth exceeded")

    monkeypatch.setattr(mapping.json, "loads", overflow)
    raises(ErrorCode.INVALID_JSON, parse_json_object, b'{"a": 1}')


def test_parsing_keeps_the_last_duplicate_key_and_preserves_json_types():
    body = parse_json_object(
        b'{"a": 1, "a": {"b": [null, true, 1, 1.5, "text"]}, "large": 9223372036854775807}'
    )
    assert body == {"a": {"b": [None, True, 1, 1.5, "text"]}, "large": 9223372036854775807}
    assert type(body["a"]["b"][2]) is int and type(body["a"]["b"][3]) is float


def test_oversized_integer_literals_are_reported_as_out_of_range():
    body = b'{"value": ' + b"1" * 5000 + b"}"
    raises(ErrorCode.VALUE_OUT_OF_RANGE, parse_json_object, body)


@pytest.mark.parametrize(
    "body",
    [
        {"\x00": "value"},
        {"nested": {"a\x00b": 1}},
        {"array": [{"\x00": 1}]},
        {"deep": {"list": [[{"a\x00": None}]]}},
    ],
)
def test_nul_object_keys_are_rejected_at_every_depth(body):
    raises(ErrorCode.INVALID_KEY, validate_json_values, body)


def test_nul_inside_string_values_remains_allowed():
    validate_json_values({"text": "a\x00b", "nested": {"list": ["\x00"]}})


@pytest.mark.parametrize("body", [{"\ud800": 1}, {"text": "\ud800"}, {"a": [{"b": "\udfff"}]}])
def test_unpaired_surrogates_are_rejected_as_invalid_fields(body):
    raises(ErrorCode.INVALID_FIELD, validate_json_values, body)


@pytest.mark.parametrize(
    "value",
    [float("nan"), float("inf"), float("-inf"), 1e999, [float("inf")], {"n": [{"m": float("nan")}]}],
)
def test_non_finite_numbers_are_rejected_anywhere_in_the_payload(value):
    raises(ErrorCode.NON_FINITE_NUMBER, validate_json_values, {"value": value})


@pytest.mark.parametrize("value", [2**63, -(2**63) - 1, 10**30, [2**63], {"n": {"m": -(2**63) - 1}}])
def test_integers_outside_signed_64_bit_range_are_rejected(value):
    raises(ErrorCode.VALUE_OUT_OF_RANGE, validate_json_values, {"value": value})


def test_signed_64_bit_boundaries_and_special_keys_are_accepted_values():
    validate_json_values({
        "min": -(2**63), "max": 2**63 - 1, "float": 1.5, "flags": [True, False, None],
        "a.b": {"$set": "$status", "_id": "nested", "__proto__": {}}, "日本語": "値",
    })


@pytest.mark.parametrize("container", ["object", "array", "mixed"])
@pytest.mark.parametrize(
    ("levels", "accepted"), [(98, True), (99, False)]
)
def test_create_envelope_depth_boundary_for_metadata_extras(container, levels, accepted):
    # Stored root is level 1 and the server metadata wrapper is level 2.
    document = {"metadata": {"extra": nested(levels, container)}}
    if accepted:
        validate_document_depth(document)
    else:
        raises(ErrorCode.PAYLOAD_TOO_DEEP, validate_document_depth, document)


@pytest.mark.parametrize("container", ["object", "array"])
@pytest.mark.parametrize(("levels", "accepted"), [(97, True), (98, False)])
def test_client_supplied_flat_metadata_adds_one_stored_level(container, levels, accepted):
    document = {"metadata": {"metadata": {"extra": nested(levels, container)}}}
    if accepted:
        validate_document_depth(document)
    else:
        raises(ErrorCode.PAYLOAD_TOO_DEEP, validate_document_depth, document)


@pytest.mark.parametrize("field", ["last_step_executed", "execution_outcome"])
@pytest.mark.parametrize(("levels", "accepted"), [(99, True), (100, False)])
def test_root_container_fields_start_at_level_two(field, levels, accepted):
    document = {field: nested(levels)}
    if accepted:
        validate_document_depth(document)
    else:
        raises(ErrorCode.PAYLOAD_TOO_DEEP, validate_document_depth, document)


def test_scalars_below_the_deepest_container_do_not_add_a_level():
    validate_document_depth({"metadata": {"extra": nested(97, "object")}})
    deepest = {"metadata": {"extra": nested(97, "object")}}
    cursor = deepest["metadata"]["extra"]
    while isinstance(cursor["k"], dict):
        cursor = cursor["k"]
    cursor["k"] = {"leaf": "scalars add no level"}
    validate_document_depth(deepest)


def test_depth_validation_reports_deeply_nested_payloads_instead_of_failing():
    raises(ErrorCode.PAYLOAD_TOO_DEEP, validate_document_depth, {"metadata": nested(5000)})


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("2026-10-01T09:07:04Z", datetime(2026, 10, 1, 9, 7, 4, tzinfo=timezone.utc)),
        ("2026-10-01T11:07:04.123999+02:00", datetime(2026, 10, 1, 9, 7, 4, 123000, tzinfo=timezone.utc)),
        ("2026-01-01T00:00:00.999999+02:00", datetime(2025, 12, 31, 22, 0, 0, 999000, tzinfo=timezone.utc)),
        ("2026-10-01T09:07:04.000999Z", datetime(2026, 10, 1, 9, 7, 4, tzinfo=timezone.utc)),
        ("2026-10-01t09:07:04z", datetime(2026, 10, 1, 9, 7, 4, tzinfo=timezone.utc)),
        ("2026-10-01T09:07:04-00:00", datetime(2026, 10, 1, 9, 7, 4, tzinfo=timezone.utc)),
    ],
)
def test_offset_aware_timestamps_normalize_to_truncated_utc(value, expected):
    parsed = parse_timestamp(value)
    assert parsed == expected
    assert parsed.tzinfo == timezone.utc
    assert parsed.microsecond % 1000 == 0


@pytest.mark.parametrize(
    "value",
    [
        "2026-10-01T09:07:04", "2026-10-01 09:07:04Z", "2026-10-01", "09:07:04Z",
        "2026-13-01T09:07:04Z", "2026-10-32T09:07:04Z", "2026-10-01T25:07:04Z",
        "2026-02-30T09:07:04Z", "2026-10-01T09:07:04+25:00", "2026-10-01T09:07:04 Z",
        "", "not a timestamp", 1790000000, 1790000000.5, True, None, [], {},
        datetime(2026, 10, 1, 9, 7, 4, tzinfo=timezone.utc),
    ],
)
def test_naive_numeric_and_malformed_timestamps_are_rejected(value):
    with pytest.raises(ValueError):
        parse_timestamp(value)


@pytest.mark.parametrize(
    "outcome",
    [
        None, {}, {"defect_count": 0}, {"gap_count": 2**63 - 1},
        {"contract_ingredient_count": 14, "unknown": {"nested": "preserved"}},
        {"debug": {"defect_count": "unknown"}}, {"notes": [None, -5, "text"]},
    ],
)
def test_outcomes_accept_supplied_counts_and_preserve_unknown_keys(outcome):
    assert validate_execution_outcome(outcome) is outcome


@pytest.mark.parametrize("field", ["defect_count", "gap_count", "contract_ingredient_count"])
@pytest.mark.parametrize("value", [-1, 2**63, True, False, "1", 1.0, None, [], {}])
def test_known_counts_are_strict_nonnegative_signed_64_bit_integers(field, value):
    with pytest.raises(ValueError):
        validate_execution_outcome({field: value})
