"""``{{var}}`` substitution for flow text (T054).

The contract's dotted placeholders, which include task results (``{{task_result.email}}``). A
variable with no value renders empty and is reported, so the call record notes it (spec edge case
"variable never set").
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from callwright_contract.variables import DOTTED_PLACEHOLDER


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

    return DOTTED_PLACEHOLDER.sub(one, text or ""), missing
