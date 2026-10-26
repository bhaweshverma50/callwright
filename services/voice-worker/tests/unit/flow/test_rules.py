"""Rule evaluator (004 T047; research R11)."""

from __future__ import annotations

from typing import Any

import pytest

from worker.flow.rules import evaluate, first_match, lookup


@pytest.mark.parametrize(
    ("operator", "actual", "expected", "result"),
    [
        ("equals", "Gold", "gold", True),
        ("equals", "10", "10.0", True),
        ("equals", "a", "b", False),
        ("not_equals", "a", "b", True),
        ("not_equals", None, "b", True),
        ("contains", "I want a refund please", "REFUND", True),
        ("contains", "hello", "bye", False),
        ("matches", "AB-1234", r"[a-z]{2}-\d{4}", True),
        ("matches", "AB-12", r"[a-z]{2}-\d{4}", False),
        ("matches", "x", "(", False),  # invalid pattern never matches
        ("exists", "x", None, True),
        ("exists", "", None, False),
        ("exists", None, None, False),
        ("gt", "18", "17", True),
        ("gt", 17, "17", False),
        ("lt", "3.5", "4", True),
        ("gt", "abc", "1", False),  # no numeric comparison for text
        ("equals", True, "true", True),
    ],
)
def test_operators(operator: str, actual: Any, expected: Any, result: bool) -> None:
    assert evaluate(operator, actual, expected) is result


def test_regex_guard_limits_size() -> None:
    assert evaluate("matches", "a" * 3000, "a+") is False
    assert evaluate("matches", "a", "a" * 600) is False


def test_lookup_reads_dotted_and_nested_task_results() -> None:
    flat = {"task_result.age": "21"}
    nested = {"task_result": {"age": 30}}
    assert lookup(flat, "task_result.age") == "21"
    assert lookup(nested, "{{task_result.age}}") == 30
    assert lookup({}, "missing") is None


def test_first_match_in_order_then_none() -> None:
    rules = [
        {"variable": "age", "operator": "gt", "value": "64", "target": "senior"},
        {"variable": "age", "operator": "gt", "value": "17", "target": "adult"},
    ]
    assert first_match(rules, {"age": 70})["target"] == "senior"  # type: ignore[index]
    assert first_match(rules, {"age": 30})["target"] == "adult"  # type: ignore[index]
    assert first_match(rules, {"age": 12}) is None
