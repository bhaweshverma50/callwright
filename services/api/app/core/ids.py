"""Prefixed ULID identifiers (architecture section 4, R19) and path-id hygiene (T091).

A malformed id in a path never reaches the database: ``path_id`` turns it into a 404
``not_found`` problem naming the record kind (FR-019).
"""

from __future__ import annotations

import inspect
import re
from collections.abc import Callable
from typing import Annotated, Any

from fastapi import Path
from ulid import ULID

PREFIXES = frozenset(
    {
        "ws",
        "usr",
        "agt",
        "agv",
        "flw",
        "tool",
        "kb",
        "doc",
        "call",
        "num",
        "wa",
        "wcr",
        "dnc",
        "whd",
        "var",
        "evl",
        "evr",
        "ann",
        "ds",
        "tc",
        "trn",
        "exp",
        "srun",
        "iss",
        "txn",
        "cbk",
        "cpf",
        "clg",
    }
)
_ULID = "[0-9A-HJKMNP-TV-Z]{26}"
_PATTERNS = {p: re.compile(rf"^{p}_{_ULID}$") for p in PREFIXES}


def new_id(prefix: str) -> str:
    if prefix not in PREFIXES:
        raise ValueError(f"unknown id prefix {prefix!r}")
    return f"{prefix}_{ULID()}"


def is_valid_id(value: str, prefix: str) -> bool:
    pattern = _PATTERNS.get(prefix)
    return bool(pattern and pattern.match(value))


def id_pattern(prefix: str) -> str:
    return _PATTERNS[prefix].pattern


def require_id(value: str, prefix: str, kind: str) -> str:
    """Return ``value`` or raise a 404 problem for ``kind`` when it is not a valid ``prefix`` id."""
    if not is_valid_id(value, prefix):
        from app.core.errors import not_found

        raise not_found(kind)
    return value


def path_id(prefix: str, kind: str, name: str) -> Callable[..., str]:
    """FastAPI dependency validating the path parameter ``name`` as a ``prefix`` id."""

    def dependency(**kwargs: Any) -> str:
        return require_id(str(kwargs[name]), prefix, kind)

    dependency.__signature__ = inspect.Signature(  # type: ignore[attr-defined]
        [inspect.Parameter(name, inspect.Parameter.KEYWORD_ONLY, annotation=Annotated[str, Path()])]
    )
    dependency.__name__ = f"path_id_{prefix}"
    return dependency
