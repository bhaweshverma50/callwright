"""``{{var}}`` parsing for flow text (T010, research R6): the contract's dotted grammar, which
also reads task results (``{{task_result.email}}``). Built-ins are set for every call and are
never reported as unset."""

from __future__ import annotations

import re
from collections.abc import Iterable

from callwright_contract.variables import BUILTIN_VARIABLES, DOTTED_PLACEHOLDER

TASK_RESULT = "task_result"


def placeholders(text: str | None) -> list[str]:
    """Variable names used in ``text``, in order of first use, without duplicates."""
    if not text:
        return []
    return list(dict.fromkeys(m.group(1) for m in DOTTED_PLACEHOLDER.finditer(text)))


def placeholders_in(texts: Iterable[str | None]) -> list[str]:
    seen: dict[str, None] = {}
    for text in texts:
        for name in placeholders(text):
            seen.setdefault(name, None)
    return list(seen)


def is_builtin(name: str) -> bool:
    return name in BUILTIN_VARIABLES


def snake_case(text: str) -> str:
    """The variable name an editor makes of a typed label ("Customer Name" -> customer_name)."""
    slug = re.sub(r"[^a-z0-9]+", "_", text.strip().lower()).strip("_")
    if slug and slug[0].isdigit():
        slug = f"v_{slug}"
    return slug[:40]
