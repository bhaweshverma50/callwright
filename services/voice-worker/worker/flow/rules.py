"""Safe rule evaluation for rule conditions (T053, research R11). No ``eval``.

Operators: ``equals``, ``not_equals``, ``contains``, ``matches`` (``re.fullmatch``), ``exists``,
``gt``, ``lt``. Both sides are compared as numbers when both parse as numbers, otherwise as
trimmed, case-insensitive text. ``matches`` is guarded: patterns and values are length-capped
and an invalid pattern never matches. Rules are checked in order; the first match wins, else
the ``else`` target.
"""

from __future__ import annotations

import functools
import re
from collections.abc import Mapping, Sequence
from typing import Any

MAX_PATTERN = 500
MAX_VALUE = 2000


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(str(value).strip())
    except ValueError:
        return None


def _text(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return "" if value is None else str(value).strip().lower()


@functools.lru_cache(maxsize=256)
def _pattern(source: str) -> re.Pattern[str] | None:
    try:
        return re.compile(source, re.IGNORECASE)
    except re.error:
        return None


def evaluate(operator: str, actual: Any, expected: Any) -> bool:
    if operator == "exists":
        return actual is not None and _text(actual) != ""
    if actual is None:
        return operator == "not_equals"
    a_num, e_num = _number(actual), _number(expected)
    if operator in ("gt", "lt"):
        if a_num is None or e_num is None:
            return False
        return a_num > e_num if operator == "gt" else a_num < e_num
    if operator in ("equals", "not_equals"):
        same = (
            a_num == e_num
            if a_num is not None and e_num is not None
            else _text(actual) == _text(expected)
        )
        return same if operator == "equals" else not same
    if operator == "contains":
        return _text(expected) in _text(actual)
    if operator == "matches":
        source = str(expected or "")
        value = str(actual)
        if len(source) > MAX_PATTERN or len(value) > MAX_VALUE:
            return False
        pattern = _pattern(source)
        return bool(pattern and pattern.fullmatch(value.strip()))
    return False


def lookup(variables: Mapping[str, Any], name: str) -> Any:
    name = name.strip().strip("{} ")
    if name in variables:
        return variables[name]
    head, _, tail = name.partition(".")
    nested = variables.get(head)
    if tail and isinstance(nested, Mapping):
        return nested.get(tail)
    return None


def first_match(
    rules: Sequence[Mapping[str, Any]], variables: Mapping[str, Any]
) -> Mapping[str, Any] | None:
    for rule in rules:
        if evaluate(
            str(rule.get("operator")),
            lookup(variables, str(rule.get("variable") or "")),
            rule.get("value"),
        ):
            return rule
    return None
