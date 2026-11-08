"""Dynamic variables (T006, FR-008, research R9)."""

from __future__ import annotations

from typing import Any

from app.agents import variables
from app.agents.defaults import default_config
from app.agents.validation import validate_pure
from app.agents.variables import NAME


def run(prompt: str, declared: list[dict[str, Any]] | None = None, greeting: str | None = None) -> Any:
    cfg = default_config("single_prompt")
    cfg["prompt"] = prompt
    cfg["begin_message"] = greeting
    cfg["dynamic_variables"] = declared or []
    return validate_pure("single_prompt", cfg)


def codes(result: Any, code: str) -> list[str]:
    return [i["pointer"] for i in result.errors + result.warnings if i["code"] == code]


def test_extracts_with_spacing() -> None:
    found = variables.extract(["Hello {{customer_name}} and {{ order_id }} and {{customer_name}}"])
    assert found.names == ("customer_name", "order_id")
    assert found.invalid == ()


def test_malformed_placeholders_flagged() -> None:
    found = variables.extract(["{{1abc}} and {{ bad name }} and {{ open"])
    assert "{{1abc}}" in found.invalid and "{{ bad name }}" in found.invalid
    assert any(raw.startswith("{{ open") for raw in found.invalid)
    assert found.names == ()


def test_auto_added_with_empty_default_and_warning() -> None:
    result = run("Hi {{customer_name}}, about {{order_id}}.")
    names = [v["name"] for v in result.normalized_config["dynamic_variables"]]
    assert names == ["customer_name", "order_id"]
    assert all(v["default"] is None for v in result.normalized_config["dynamic_variables"])
    assert codes(result, "variable_without_default") == [
        "/dynamic_variables[customer_name]/default",
        "/dynamic_variables[order_id]/default",
    ]


def test_greeting_placeholders_count() -> None:
    result = run("Prompt.", greeting="Hello {{caller}}")
    assert [v["name"] for v in result.normalized_config["dynamic_variables"]] == ["caller"]


def test_invalid_names_flagged_and_not_added() -> None:
    result = run("Hi {{1abc}} and {{ name")
    assert result.normalized_config["dynamic_variables"] == []
    assert codes(result, "invalid_variable")


def test_hand_added_bad_name_refused() -> None:
    result = run("Hello {{order_id}}", [{"name": "bad name!", "default": "x"}])
    assert codes(result, "invalid_variable") == ["/dynamic_variables[bad name!]/name"]
    assert not result.valid


def test_reserved_names() -> None:
    result = run("It is {{current_time}}.", [{"name": "call_id", "default": "x"}])
    assert codes(result, "reserved_variable") == ["/dynamic_variables[call_id]/name"]
    assert "current_time" not in [v["name"] for v in result.normalized_config["dynamic_variables"]]
    assert variables.is_reserved("current_datetime") and not variables.is_reserved("customer")


def test_max_fifty() -> None:
    result = run("Hello", [{"name": f"v{i}", "default": "x"} for i in range(51)])
    assert "/dynamic_variables" in [e["pointer"] for e in result.errors]


def test_max_length_name() -> None:
    assert variables.is_valid_name("a" * 64)
    assert not variables.is_valid_name("a" * 65)
    assert variables.is_valid_name("_private")


def test_unused_default_kept_and_marked() -> None:
    result = run("Hello", [{"name": "old_var", "default": "x"}])
    assert result.valid
    assert [v["name"] for v in result.normalized_config["dynamic_variables"]] == ["old_var"]
    assert codes(result, "unused_default") == ["/dynamic_variables[old_var]/default"]


def test_duplicates_refused() -> None:
    result = run("Hello {{a}}", [{"name": "a", "default": "1"}, {"name": "a", "default": "2"}])
    assert codes(result, "duplicate_entry") == ["/dynamic_variables[a]/name"]


def test_flow_text_counts() -> None:
    cfg = default_config("flow")
    cfg["flow"] = {"graph": {"nodes": [{"prompt": "Ask {{account_no}}"}]}}
    result = validate_pure("flow", cfg)
    assert [v["name"] for v in result.normalized_config["dynamic_variables"]] == ["account_no"]


def test_name_rule() -> None:
    assert NAME.match("_a1") and NAME.match("a" * 64)
    assert not NAME.match("1a") and not NAME.match("a" * 65) and not NAME.match("a-b")
