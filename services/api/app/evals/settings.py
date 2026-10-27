"""Effective evaluator settings, schema validation and headline rules (007 T036, T084;
FR-008, FR-036, FR-038, FR-039, data-model "Settings validation").

* ``served_schema`` fills judge model options from ``EVAL_JUDGE_MODELS`` and renders ``{default}``
  in helper texts, so a helper can never disagree with the field default.
* ``validate_overrides`` rejects unknown keys, non-integers for ``int``, values outside
  ``[min, max]`` and select values outside the options, with one message per field.
* ``effective`` overlays stored overrides on the defaults and clamps any value a newer version's
  range no longer allows, reporting it in ``adjusted_fields``.
"""

from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any

from app.core.errors import field_error

MAX_HEADLINE = 4
HEADLINE_LIMIT_MESSAGE = "Up to 4 headline checks per agent"


def fmt(value: Any) -> str:
    if isinstance(value, bool):
        return "on" if value else "off"
    if isinstance(value, int) or (isinstance(value, float) and value.is_integer() and abs(value) >= 1):
        return f"{int(value):,}"
    if isinstance(value, float):
        return f"{value:g}"
    return str(value)


def served_schema(schema: Mapping[str, Any], judge_models: Sequence[str]) -> dict[str, Any]:
    out = copy.deepcopy(dict(schema))
    fields = []
    for raw in out.get("fields") or []:
        f = dict(raw)
        if f.get("options_source") == "judge_models":
            f["options"] = list(judge_models)
            if f.get("default") in (None, ""):
                f["default"] = judge_models[0]
        if isinstance(f.get("helper"), str):
            f["helper"] = f["helper"].replace("{default}", fmt(f.get("default")))
        fields.append(f)
    out["fields"] = fields
    return out


def _range_message(f: Mapping[str, Any]) -> str:
    lo, hi = f.get("min"), f.get("max")
    if f["type"] == "int":
        return f"Enter a whole number from {fmt(lo)} to {fmt(hi)}"
    return f"Enter a number from {fmt(lo)} to {fmt(hi)}"


def validate_overrides(schema: Mapping[str, Any], overrides: Any) -> list[dict[str, str]]:
    """Field errors for ``overrides`` against a *served* schema (options already filled)."""
    if overrides is None:
        return []
    if not isinstance(overrides, Mapping):
        return [field_error("/overrides", "invalid_format", "Settings must be an object")]
    fields = {f["key"]: f for f in schema.get("fields") or []}
    errors: list[dict[str, str]] = []
    for key, value in overrides.items():
        pointer = f"/overrides/{key}"
        f = fields.get(key)
        if f is None:
            errors.append(field_error(pointer, "unknown_field", f"Unknown setting {key}"))
            continue
        kind = f["type"]
        if kind in ("int", "number"):
            is_number = isinstance(value, int | float) and not isinstance(value, bool)
            whole = is_number and float(value).is_integer()
            lo, hi = f.get("min"), f.get("max")
            if (
                not is_number
                or (kind == "int" and not whole)
                or (lo is not None and value < lo)
                or (hi is not None and value > hi)
            ):
                errors.append(field_error(pointer, "out_of_range", _range_message(f)))
        elif kind == "select":
            if value not in (f.get("options") or []):
                message = (
                    "Pick one of the listed judge models"
                    if f.get("options_source") == "judge_models"
                    else "Pick one of the listed options"
                )
                errors.append(field_error(pointer, "not_in_catalog", message))
        elif kind == "bool":
            if not isinstance(value, bool):
                errors.append(field_error(pointer, "invalid_format", "Choose on or off"))
        elif not isinstance(value, str) or (kind == "text" and len(value) > 500) or len(value) > 5000:
            errors.append(field_error(pointer, "out_of_range", "Enter a shorter text"))
    return errors


def effective(
    schema: Mapping[str, Any], overrides: Mapping[str, Any] | None
) -> tuple[dict[str, Any], list[str]]:
    """Defaults overlaid with overrides; out-of-range stored values clamped (``adjusted``)."""
    values: dict[str, Any] = {}
    adjusted: list[str] = []
    stored = dict(overrides or {})
    for f in schema.get("fields") or []:
        key = f["key"]
        value = stored.get(key, f.get("default"))
        kind = f["type"]
        if kind in ("int", "number") and isinstance(value, int | float) and not isinstance(value, bool):
            lo, hi = f.get("min"), f.get("max")
            clamped = value
            if lo is not None and clamped < lo:
                clamped = lo
            if hi is not None and clamped > hi:
                clamped = hi
            if kind == "int":
                clamped = round(clamped)
            if clamped != value and key in stored:
                adjusted.append(key)
            value = clamped
        elif kind == "select" and f.get("options") and value not in f["options"]:
            if key in stored:
                adjusted.append(key)
            value = f.get("default")
        values[key] = value
    return values, adjusted


def settings_hash(values: Mapping[str, Any]) -> str:
    return hashlib.sha256(json.dumps(values, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
