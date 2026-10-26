"""``{{var}}`` substitution for flow text (T054).

Same placeholders as the API (``app.flows.variables``), including dotted task results
(``{{task_result.email}}``). A variable with no value renders empty and is reported, so the
call record notes it (spec edge case "variable never set").
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

PLACEHOLDER = re.compile(
    r"\{\{\s*([A-Za-z_][A-Za-z0-9_]{0,63}(?:\.[A-Za-z_][A-Za-z0-9_]{0,63})?)\s*\}\}"
)


def as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def render(text: str | None, variables: Mapping[str, Any]) -> tuple[str, list[str]]:
    """``text`` with placeholders replaced, and the names that had no value."""
    missing: list[str] = []

    def one(match: re.Match[str]) -> str:
        name = match.group(1)
        value = variables.get(name)
        if value is None or value == "":
            if name not in missing:
                missing.append(name)
            return ""
        return as_text(value)

    return PLACEHOLDER.sub(one, text or ""), missing
