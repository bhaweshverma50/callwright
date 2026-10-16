"""Dynamic variables: placeholder extraction and naming rules (T013, FR-008, research R9).

Placeholders are ``{{name}}`` with optional spaces inside the braces. Names start with a letter
or underscore and contain letters, digits and underscores (max 64 characters). Built-in names
(resolved by 003 at call time) may appear in text but cannot be declared.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
PLACEHOLDER_RE = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]{0,63})\s*\}\}")
_ANY_BRACES_RE = re.compile(r"\{\{(.*?)\}\}", re.DOTALL)
MAX_VARIABLES = 50
MAX_DEFAULT_LENGTH = 2000
MAX_DESCRIPTION_LENGTH = 200

RESERVED_NAMES = frozenset(
    {
        "call_id",
        "channel",
        "direction",
        "user_number",
        "agent_number",
        "timezone",
        "current_time",
        "current_date",
        "current_datetime",
    }
)


@dataclass(frozen=True)
class Placeholders:
    names: tuple[str, ...]
    """Valid placeholder names in order of first appearance (reserved names included)."""
    invalid: tuple[str, ...]
    """Raw text of malformed placeholders such as ``{{ name`` or ``{{1abc}}``."""


def is_valid_name(name: str) -> bool:
    return bool(NAME_RE.match(name))


def is_reserved(name: str) -> bool:
    return name in RESERVED_NAMES


def extract(texts: Iterable[str | None]) -> Placeholders:
    names: list[str] = []
    invalid: list[str] = []
    for text in texts:
        if not text:
            continue
        for match in PLACEHOLDER_RE.finditer(text):
            if match.group(1) not in names:
                names.append(match.group(1))
        stripped = PLACEHOLDER_RE.sub("", text)
        for match in _ANY_BRACES_RE.finditer(stripped):
            raw = match.group(0)
            if raw not in invalid:
                invalid.append(raw)
        leftover = _ANY_BRACES_RE.sub("", stripped)
        if "{{" in leftover:
            start = leftover.index("{{")
            fragment = leftover[start : start + 24].split("\n")[0]
            if fragment not in invalid:
                invalid.append(fragment)
    return Placeholders(tuple(names), tuple(invalid))


def usable_names(texts: Iterable[str | None]) -> list[str]:
    """Placeholder names that belong in the variables list (valid and not built-in)."""
    return [n for n in extract(texts).names if not is_reserved(n)]
