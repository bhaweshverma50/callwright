"""Dynamic variables: placeholder extraction and naming rules (T013, FR-008, research R9).

Placeholders are ``{{name}}`` with optional spaces inside the braces. Names start with a letter
or underscore and contain letters, digits and underscores (max 64 characters). Built-in names
(resolved by 003 at call time) may appear in text but cannot be declared.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

from callwright_contract.variables import BUILTIN_VARIABLES, PLACEHOLDER

NAME_PATTERN = r"^[A-Za-z_][A-Za-z0-9_]{0,63}$"
NAME = re.compile(NAME_PATTERN)
MAX_VARIABLES = 50
MAX_VALUE_CHARS = 2000
MAX_DESCRIPTION_CHARS = 200
_ANY_BRACES_RE = re.compile(r"\{\{(.*?)\}\}", re.DOTALL)


@dataclass(frozen=True)
class Placeholders:
    names: tuple[str, ...]
    """Valid placeholder names in order of first appearance (reserved names included)."""
    invalid: tuple[str, ...]
    """Raw text of malformed placeholders such as ``{{ name`` or ``{{1abc}}``."""


def is_valid_name(name: str) -> bool:
    return bool(NAME.match(name))


def is_reserved(name: str) -> bool:
    return name in BUILTIN_VARIABLES


def extract(texts: Iterable[str | None]) -> Placeholders:
    names: list[str] = []
    invalid: list[str] = []
    for text in texts:
        if not text:
            continue
        for match in PLACEHOLDER.finditer(text):
            if match.group(1) not in names:
                names.append(match.group(1))
        stripped = PLACEHOLDER.sub("", text)
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
