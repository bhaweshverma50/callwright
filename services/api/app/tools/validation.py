"""Tool validation (T010): names, config shape per type, JSON Schema parameters, URL rules.

Every function returns field issues ``{pointer, code, message}`` (the 001 problem format), so
the router can answer one 422 that names every bad field at once.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlsplit

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from pydantic import BaseModel, ValidationError

from app.tools.schemas import (
    CONFIG_MODELS,
    NAME_PATTERN,
    RESERVED_NAMES,
    RESERVED_PREFIXES,
)

Issue = dict[str, str]
_NAME = re.compile(NAME_PATTERN)
_PLACEHOLDER = re.compile(r"\{\{\s*[A-Za-z_][A-Za-z0-9_.]*\s*\}\}")
MAX_SCHEMA_DEPTH = 5
MAX_SCHEMA_PROPERTIES = 30


def issue(pointer: str, code: str, message: str) -> Issue:
    return {"pointer": pointer, "code": code, "message": message}


def validate_name(name: str, pointer: str = "/name") -> list[Issue]:
    if not _NAME.match(name or ""):
        return [
            issue(
                pointer,
                "invalid_format",
                "Use 1 to 64 lowercase letters, digits or underscores, starting with a letter.",
            )
        ]
    if name in RESERVED_NAMES:
        return [issue(pointer, "reserved_name", f"{name} is reserved for knowledge search.")]
    for prefix in RESERVED_PREFIXES:
        if name.startswith(prefix):
            return [issue(pointer, "reserved_name", f"Names starting with {prefix} are reserved for flows.")]
    return []


def _pointer(base: str, loc: tuple[int | str, ...]) -> str:
    return base + "".join(f"/{p}" for p in loc)


def _pydantic_issues(exc: ValidationError, base: str) -> list[Issue]:
    out: list[Issue] = []
    for err in exc.errors():
        loc = tuple(err.get("loc", ()))
        etype = str(err.get("type", ""))
        message = str(err.get("msg", "Invalid value"))
        if message.startswith("Value error, "):
            message = message[len("Value error, ") :]
        if etype == "extra_forbidden":
            out.append(
                issue(_pointer(base, loc), "unknown_field", f"{loc[-1]} is not a field of this tool type.")
            )
            continue
        if etype == "missing":
            out.append(issue(_pointer(base, loc), "required", "This field is required."))
            continue
        if etype == "value_error" and ": " in message and not loc:
            field, _, text = message.partition(": ")
            out.append(issue(_pointer(base, (field,)), "required", text))
            continue
        code = "out_of_range" if etype.endswith(("_than", "_than_equal")) else "invalid_format"
        if etype.startswith("too_"):
            code = "out_of_range"
        out.append(issue(_pointer(base, loc), code, message))
    return out


def parse_config(tool_type: str, config: Mapping[str, Any]) -> tuple[BaseModel | None, list[Issue]]:
    model = CONFIG_MODELS[tool_type]
    try:
        return model.model_validate(dict(config)), []
    except ValidationError as exc:
        return None, _pydantic_issues(exc, "/config")


def _depth(node: Any, level: int = 0) -> int:
    if isinstance(node, Mapping):
        return max([level, *(_depth(v, level + 1) for v in node.values())])
    if isinstance(node, list):
        return max([level, *(_depth(v, level + 1) for v in node)])
    return level


def _property_count(node: Any) -> int:
    count = 0
    if isinstance(node, Mapping):
        props = node.get("properties")
        if isinstance(props, Mapping):
            count += len(props)
        count += sum(_property_count(v) for v in node.values())
    elif isinstance(node, list):
        count += sum(_property_count(v) for v in node)
    return count


def validate_parameters(schema: Any, pointer: str = "/config/parameters") -> list[Issue]:
    """The parameters schema must be a valid Draft 2020-12 schema of ``type: object``."""
    if not isinstance(schema, Mapping) or schema.get("type") != "object":
        return [issue(pointer, "invalid_schema", "Parameters must be a JSON Schema with type object.")]
    try:
        Draft202012Validator.check_schema(dict(schema))
    except SchemaError as exc:
        return [issue(pointer, "invalid_schema", f"Not a valid JSON Schema: {exc.message}")]
    # Each nesting level of the schema adds two levels of JSON (properties -> name -> schema).
    if _depth(schema) > MAX_SCHEMA_DEPTH * 2 + 1:
        return [issue(pointer, "too_deep", f"Parameters may nest at most {MAX_SCHEMA_DEPTH} levels.")]
    if _property_count(schema) > MAX_SCHEMA_PROPERTIES:
        return [
            issue(
                pointer, "too_many_properties", f"Parameters may have at most {MAX_SCHEMA_PROPERTIES} fields."
            )
        ]
    return []


def validate_url(url: str, *, allow_http: bool, pointer: str = "/config/url") -> list[Issue]:
    """Absolute https URL (http only in development); placeholders only in path and query."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return [issue(pointer, "invalid_url", "Enter a full URL such as https://api.example.com/path.")]
    scheme = parts.scheme.lower()
    if scheme not in ("https", "http") or not parts.netloc:
        return [issue(pointer, "invalid_url", "Enter a full URL such as https://api.example.com/path.")]
    if scheme == "http" and not allow_http:
        return [issue(pointer, "https_required", "The URL must start with https://.")]
    if _PLACEHOLDER.search(parts.netloc) or "{" in parts.netloc:
        return [issue(pointer, "invalid_url", "Placeholders are allowed in the path and query only.")]
    if parts.username or parts.password:
        return [issue(pointer, "invalid_url", "Credentials in the URL are not allowed; use a secret header.")]
    return []


def validate_config(tool_type: str, config: Mapping[str, Any], *, allow_http: bool) -> list[Issue]:
    parsed, issues = parse_config(tool_type, config)
    if parsed is None or tool_type != "http":
        return issues
    data = parsed.model_dump()
    issues += validate_url(str(data["url"]), allow_http=allow_http)
    issues += validate_parameters(data["parameters"])
    seen: set[str] = set()
    for i, header in enumerate(data["headers"]):
        lowered = str(header["name"]).lower()
        if lowered in seen:
            issues.append(issue(f"/config/headers/{i}/name", "duplicate", "This header is listed twice."))
        seen.add(lowered)
        if not header["secret"] and header.get("value") is None:
            issues.append(issue(f"/config/headers/{i}/value", "required", "Enter a value for this header."))
    names = [m["variable_name"] for m in data["response_mappings"]]
    for i, name in enumerate(names):
        if names.index(name) != i:
            issues.append(
                issue(
                    f"/config/response_mappings/{i}/variable_name",
                    "duplicate",
                    "This variable is mapped twice.",
                )
            )
    return issues


def validate_mock(tool_type: str, mock_response: str | None) -> list[Issue]:
    if mock_response is not None and tool_type != "http":
        return [
            issue(
                "/mock_response",
                "not_allowed",
                "Only HTTP tools have a canned response; other types have fixed simulated outcomes.",
            )
        ]
    return []


def validate_tool(
    tool_type: str, name: str, config: Mapping[str, Any], mock_response: str | None, *, allow_http: bool
) -> list[Issue]:
    return (
        validate_name(name)
        + validate_config(tool_type, config, allow_http=allow_http)
        + validate_mock(tool_type, mock_response)
    )
