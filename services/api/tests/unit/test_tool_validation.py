"""Tool validation (005 T009): names, reserved names, E.164, parameters schema, URL and headers."""

from __future__ import annotations

from typing import Any

import pytest

from app.tools.schemas import DEFAULT_HOLD_MESSAGE, with_config_defaults
from app.tools.validation import (
    validate_config,
    validate_mock,
    validate_name,
    validate_parameters,
    validate_tool,
    validate_url,
)


def codes(issues: list[dict[str, str]]) -> list[tuple[str, str]]:
    return [(i["pointer"], i["code"]) for i in issues]


@pytest.mark.parametrize("name", ["end_call", "a", "check_availability_2", "x" * 64])
def test_valid_names(name: str) -> None:
    assert validate_name(name) == []


@pytest.mark.parametrize("name", ["", "End", "1tool", "has-dash", "x" * 65, "with space"])
def test_invalid_names(name: str) -> None:
    assert codes(validate_name(name)) == [("/name", "invalid_format")]


@pytest.mark.parametrize("name", ["kb_search", "route_to_billing"])
def test_reserved_names(name: str) -> None:
    assert codes(validate_name(name)) == [("/name", "reserved_name")]


def test_static_transfer_needs_e164() -> None:
    assert codes(validate_config("transfer_call", {"number": "555-1234"}, allow_http=False)) == [
        ("/config/number", "invalid_format")
    ]
    assert validate_config("transfer_call", {"number": "+14155550100"}, allow_http=False) == []
    assert codes(validate_config("transfer_call", {}, allow_http=False)) == [("/config/number", "required")]


def test_dynamic_transfer_needs_instructions_and_valid_allow_list() -> None:
    ok = {
        "routing_type": "dynamic",
        "routing_instructions": "Sales or support",
        "allowed_numbers": ["+14155550100"],
    }
    assert validate_config("transfer_call", ok, allow_http=False) == []
    bad = {**ok, "allowed_numbers": ["0800"]}
    assert codes(validate_config("transfer_call", bad, allow_http=False)) == [
        ("/config/allowed_numbers/0", "invalid_format")
    ]
    assert codes(validate_config("transfer_call", {"routing_type": "dynamic"}, allow_http=False)) == [
        ("/config/routing_instructions", "required")
    ]
    no_list = {**ok, "allowed_numbers": []}
    assert codes(validate_config("transfer_call", no_list, allow_http=False)) == [
        ("/config/allowed_numbers", "required")
    ]


def test_warm_transfer_needs_briefing() -> None:
    cfg = {"number": "+14155550100", "transfer_type": "warm"}
    assert codes(validate_config("transfer_call", cfg, allow_http=False)) == [
        ("/config/warm_transfer", "required")
    ]


def test_unknown_or_legacy_config_keys_are_named() -> None:
    cfg = {"number": "+14155550100", "transfer_destination": {"number": "+14155550100"}}
    assert codes(validate_config("transfer_call", cfg, allow_http=False)) == [
        ("/config/transfer_destination", "unknown_field")
    ]


def test_press_digit_ranges() -> None:
    assert validate_config("press_digit", {}, allow_http=False) == []
    assert codes(validate_config("press_digit", {"delay_ms": 20000}, allow_http=False)) == [
        ("/config/delay_ms", "out_of_range")
    ]


def http(**changes: Any) -> dict[str, Any]:
    return {"url": "https://api.example.com/slots", **changes}


def test_http_defaults_are_valid() -> None:
    assert validate_config("http", http(), allow_http=False) == []


def test_https_rule_outside_development() -> None:
    assert codes(validate_url("http://api.example.com", allow_http=False)) == [
        ("/config/url", "https_required")
    ]
    assert validate_url("http://api.example.com", allow_http=True) == []
    assert codes(validate_url("api.example.com/x", allow_http=True)) == [("/config/url", "invalid_url")]


def test_placeholders_only_in_path_and_query() -> None:
    assert validate_url("https://api.example.com/p/{{id}}?d={{date}}", allow_http=False) == []
    assert codes(validate_url("https://{{host}}.example.com/", allow_http=False)) == [
        ("/config/url", "invalid_url")
    ]


def test_parameters_must_be_object_schema() -> None:
    assert codes(validate_parameters({"type": "string"})) == [("/config/parameters", "invalid_schema")]
    assert codes(validate_parameters({"type": "object", "properties": {"a": {"type": "nope"}}})) == [
        ("/config/parameters", "invalid_schema")
    ]
    good = {"type": "object", "properties": {"date": {"type": "string"}}, "required": ["date"]}
    assert validate_parameters(good) == []


def test_parameters_depth_and_size_limits() -> None:
    node: dict[str, Any] = {"type": "string"}
    for _ in range(7):
        node = {"type": "object", "properties": {"x": node}}
    assert codes(validate_parameters(node)) == [("/config/parameters", "too_deep")]
    wide = {"type": "object", "properties": {f"p{i}": {"type": "string"} for i in range(31)}}
    assert codes(validate_parameters(wide)) == [("/config/parameters", "too_many_properties")]


def test_header_names_and_duplicates() -> None:
    bad = http(headers=[{"name": "Bad Header", "value": "x"}])
    assert codes(validate_config("http", bad, allow_http=False)) == [
        ("/config/headers/0/name", "invalid_format")
    ]
    dup = http(headers=[{"name": "X-A", "value": "1"}, {"name": "x-a", "value": "2"}])
    assert codes(validate_config("http", dup, allow_http=False)) == [("/config/headers/1/name", "duplicate")]


def test_mock_only_for_http() -> None:
    assert validate_mock("http", "{}") == []
    assert codes(validate_mock("end_call", "{}")) == [("/mock_response", "not_allowed")]


def test_validate_tool_collects_every_issue() -> None:
    found = validate_tool("end_call", "Bad", {"messag": "x"}, "{}", allow_http=False)
    assert codes(found) == [
        ("/name", "invalid_format"),
        ("/config/messag", "unknown_field"),
        ("/mock_response", "not_allowed"),
    ]


def test_snapshot_configs_carry_every_schema_default() -> None:
    """A version snapshot names every value, so the worker keeps no defaults of its own."""
    transfer = with_config_defaults("transfer_call", {"number": "+14155550100", "ring_timeout_s": 45})
    assert transfer["ring_timeout_s"] == 45 and transfer["hold_message"] == DEFAULT_HOLD_MESSAGE
    assert with_config_defaults("press_digit", {}) == {"delay_ms": 1000, "cooldown_ms": 5000}
    http = with_config_defaults("http", {"url": "https://api.example.com"})
    assert http["speak_during_execution"] is True and http["timeout_ms"] == 8000
    assert http["headers"] == [{"name": "Content-Type", "value": "application/json", "secret": False}]
