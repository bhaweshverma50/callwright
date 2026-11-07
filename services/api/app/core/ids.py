"""Prefixed ULID identifiers (architecture section 4, R19) and path-id hygiene (T091).

A malformed id in a path never reaches the database: ``path_id`` turns it into a 404
``not_found`` problem naming the record kind (FR-019).
"""

from __future__ import annotations

import inspect
import re
from collections.abc import Callable
from functools import cache
from typing import Annotated, Any

from fastapi import Path
from ulid import ULID

_ULID = "[0-9A-HJKMNP-TV-Z]{26}"
_PREFIX = re.compile(r"^[a-z]+$")


@cache
def _pattern(prefix: str) -> re.Pattern[str]:
    return re.compile(rf"^{prefix}_{_ULID}$")


def new_id(prefix: str) -> str:
    """Prefixes are declared by the owning feature's manifest (``Feature.id_prefixes``)."""
    if not _PREFIX.match(prefix):
        raise ValueError(f"invalid id prefix {prefix!r}")
    return f"{prefix}_{ULID()}"


def is_valid_id(value: str, prefix: str) -> bool:
    return bool(_PREFIX.match(prefix) and _pattern(prefix).match(value))


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
