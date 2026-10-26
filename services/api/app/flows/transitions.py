"""Transition naming and descriptions (T037, T110; data-model section 4, research R7, FR-044).

``derive_name("Route To Billing!")`` is ``route_to_billing``; a label with no letter or digit
derives nothing (``None``). The web edge panel keeps an identical TypeScript copy, checked
against the shared vectors in ``tests/unit/flows/fixtures/transition_names.json``.
"""

from __future__ import annotations

import re

PREFIX = "route_to_"
MAX_SLUG = 48
_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def slug(label: str | None) -> str:
    text = _NON_ALNUM.sub("_", (label or "").lower()).strip("_")
    if text.startswith(PREFIX):
        text = text[len(PREFIX) :]
    elif text == PREFIX.rstrip("_"):
        text = ""
    return text[:MAX_SLUG].strip("_")


def derive_name(label: str | None) -> str | None:
    """The function name the model sees for an edge label, or None when the label is empty."""
    s = slug(label)
    return f"{PREFIX}{s}" if s else None


def function_name(label: str | None, override: str | None = None) -> str | None:
    return override or derive_name(label)


def description(target_label: str, condition: str | None) -> str:
    text = f"Go to {target_label}."
    if condition and condition.strip():
        text += f" Use when: {condition.strip()}"
    return text
