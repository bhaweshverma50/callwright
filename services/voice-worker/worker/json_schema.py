"""A small JSON Schema check: type, const, enum, anyOf, $ref (to ``#/$defs``), pattern, lengths,
ranges, required, properties, additionalProperties and items. It checks the compiled flow a call
runs against ``compiled_schema.json`` (004) and, without the combining keywords (``const``,
``anyOf``, ``$ref``, ``additionalProperties``), the arguments the model passes to a tool (005).

It stays beside the ``jsonschema`` library the API uses: it treats a null as an absent value
(models send null for optional arguments) and words each problem for the model to read back,
which the library's errors and its all-or-nothing keyword set do not.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

_TYPES: Mapping[str, tuple[type, ...]] = {
    "string": (str,),
    "integer": (int,),
    "number": (int, float),
    "boolean": (bool,),
    "object": (dict,),
    "array": (list,),
    "null": (type(None),),
}


def _type_ok(value: Any, expected: Any) -> bool:
    names = expected if isinstance(expected, list) else [expected]
    for name in names:
        kinds = _TYPES.get(str(name))
        if kinds is None:
            return True
        if isinstance(value, bool) and name in ("integer", "number"):
            continue
        if isinstance(value, kinds):
            return True
    return False


def _resolve(schema: Mapping[str, Any], root: Mapping[str, Any]) -> Mapping[str, Any]:
    ref = schema.get("$ref")
    if not isinstance(ref, str) or not ref.startswith("#/$defs/"):
        return schema
    resolved: Mapping[str, Any] = root["$defs"][ref.removeprefix("#/$defs/")]
    return resolved


def problem(
    schema: Mapping[str, Any],
    value: Any,
    path: str = "",
    *,
    combining: bool = True,
    root: Mapping[str, Any] | None = None,
) -> str | None:
    """The first way ``value`` breaks ``schema``, as a short sentence, or None. ``combining``
    False skips ``const``, ``anyOf``, ``$ref`` and ``additionalProperties``."""
    root = root if root is not None else schema
    if combining:
        schema = _resolve(schema, root)
    where = path or "arguments"

    def inner(sub: Mapping[str, Any], item: Any, at: str) -> str | None:
        return problem(sub, item, at, combining=combining, root=root)

    if (
        combining
        and "anyOf" in schema
        and all(inner(o, value, path) for o in schema["anyOf"] if isinstance(o, Mapping))
    ):
        return f"{where} has the wrong form"
    if "type" in schema and not _type_ok(value, schema["type"]):
        return f"{where} must be {schema['type']}"
    if combining and "const" in schema and value != schema["const"]:
        return f"{where} must be {schema['const']}"
    if "enum" in schema and value not in schema["enum"]:
        return f"{where} must be one of {schema['enum']}"
    if isinstance(value, str):
        if "pattern" in schema and not re.search(str(schema["pattern"]), value):
            return f"{where} has the wrong format"
        if len(value) < int(schema.get("minLength", 0)):
            return f"{where} is too short"
        if "maxLength" in schema and len(value) > int(schema["maxLength"]):
            return f"{where} is too long"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            return f"{where} is below {schema['minimum']}"
        if "maximum" in schema and value > schema["maximum"]:
            return f"{where} is above {schema['maximum']}"
    if isinstance(value, dict):
        for name in schema.get("required") or []:
            if name not in value or value[name] is None:
                return f"{name} is required"
        props = schema.get("properties") or {}
        extra = schema.get("additionalProperties") if combining else None
        names = [*[n for n in props if n in value], *[n for n in value if n not in props]]
        for name in names:
            item, sub = value[name], props.get(name, extra)
            if item is not None and isinstance(sub, Mapping):
                found = inner(sub, item, f"{path}.{name}" if path else name)
                if found:
                    return found
    if isinstance(value, list) and isinstance(schema.get("items"), Mapping):
        for i, item in enumerate(value):
            found = inner(schema["items"], item, f"{where}[{i}]")
            if found:
                return found
    return None
