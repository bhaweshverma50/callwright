"""``{{var}}`` parsing and the built-in variable list (T010, research R6).

Placeholders match the worker's renderer (``worker.pipeline.PLACEHOLDER``) plus dotted names for
task results (``{{task_result.email}}``). Built-ins are filled by the runtime for every call and
are never reported as unset.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

PLACEHOLDER = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]{0,63}(?:\.[A-Za-z_][A-Za-z0-9_]{0,63})?)\s*\}\}")

BUILTIN_VARIABLES: tuple[str, ...] = (
    "call_id",
    "direction",
    "channel",
    "from_number",
    "to_number",
    "timezone",
    "current_time",
    "current_date",
    "current_datetime",
    "agent_name",
)

TASK_RESULT = "task_result"


def placeholders(text: str | None) -> list[str]:
    """Variable names used in ``text``, in order of first use, without duplicates."""
    if not text:
        return []
    return list(dict.fromkeys(m.group(1) for m in PLACEHOLDER.finditer(text)))


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
