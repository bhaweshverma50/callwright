"""``{{var}}`` parsing and built-ins (004 T009)."""

from __future__ import annotations

from app.flows.variables import is_builtin, placeholders, placeholders_in, snake_case


def test_placeholders_in_order_without_duplicates() -> None:
    assert placeholders("Hi {{ name }}, born {{dob}}. {{name}}") == ["name", "dob"]


def test_dotted_task_results_are_variables() -> None:
    assert placeholders("Email: {{task_result.email}}") == ["task_result.email"]


def test_invalid_placeholders_are_ignored() -> None:
    assert placeholders("{{1abc}} {{}} {{a b}} {name}") == []


def test_placeholders_across_texts() -> None:
    assert placeholders_in(["{{a}}", None, "{{b}} {{a}}"]) == ["a", "b"]


def test_builtins_are_the_contract_list() -> None:
    assert is_builtin("user_number") and is_builtin("call_id") and not is_builtin("dob")
    assert not is_builtin("from_number")


def test_snake_case_conversion() -> None:
    assert snake_case("Customer Name") == "customer_name"
    assert snake_case("  Date of Birth! ") == "date_of_birth"
    assert snake_case("2nd phone") == "v_2nd_phone"
