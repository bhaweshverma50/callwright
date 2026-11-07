"""HTTP tool core: templating, argument placement, redirects, response mapping and payloads
(005 research R4 to R6).

Shared by the API's editor test runs (``app.tools.http_exec``) and the worker's executor on calls
(``worker.tools.http``), so both agree; ``tests/http_exec_vectors.json`` pins the behaviour.

Placeholders are ``{{name}}`` with names ``[A-Za-z_][A-Za-z0-9_.]*``, looked up in the call's
dynamic variables, then the LLM arguments, then variables mapped by earlier tools. The body
template is JSON: placeholders are substituted inside string values only, and a string that is
exactly one placeholder takes the variable's JSON type, so caller speech can never change the
JSON structure. URL placeholders are percent-encoded.
"""

from __future__ import annotations

import json
import re
from collections.abc import AsyncIterable, Mapping
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote, urlencode, urlsplit, urlunsplit

PLACEHOLDER = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_.]*)\s*\}\}")
WHOLE = re.compile(r"^\s*\{\{\s*([A-Za-z_][A-Za-z0-9_.]*)\s*\}\}\s*$")
_PATH_TOKEN = re.compile(r"([^.\[\]]+)|\[(\d+)\]")
MAX_RESPONSE_BYTES = 64 * 1024
MAX_LLM_PAYLOAD_CHARS = 4000
QUERY_METHODS = frozenset({"GET", "DELETE"})
DEFAULT_TIMEOUT_MS = 8000
MAX_REDIRECTS = 3
REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
_MISSING = object()


class Variables:
    """Lookup in order: dynamic variables, arguments, mapped variables (R6). Call variables come
    first so the model can never override a platform value such as ``user_number`` (016 FR-022)."""

    def __init__(
        self,
        arguments: Mapping[str, Any],
        dynamic: Mapping[str, Any] | None = None,
        mapped: Mapping[str, Any] | None = None,
    ) -> None:
        self.sources = (dynamic or {}, arguments, mapped or {})
        self.missing: list[str] = []

    def get(self, name: str) -> Any:
        for source in self.sources:
            value = _dig(source, name)
            if value is not _MISSING:
                return value
        if name not in self.missing:
            self.missing.append(name)
        return _MISSING


def _dig(source: Mapping[str, Any], name: str) -> Any:
    if name in source:
        return source[name]
    node: Any = source
    for part in name.split("."):
        if isinstance(node, Mapping) and part in node:
            node = node[part]
        else:
            return _MISSING
    return node


def _as_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False)


def render_text(template: str, variables: Variables, *, url_encode: bool = False) -> str:
    def repl(match: re.Match[str]) -> str:
        value = variables.get(match.group(1))
        if value is _MISSING:
            return ""
        text = _as_text(value)
        return quote(text, safe="") if url_encode else text

    return PLACEHOLDER.sub(repl, template)


def render_value(template: Any, variables: Variables) -> Any:
    if isinstance(template, str):
        whole = WHOLE.match(template)
        if whole:
            value = variables.get(whole.group(1))
            return None if value is _MISSING else value
        return render_text(template, variables)
    if isinstance(template, list):
        return [render_value(v, variables) for v in template]
    if isinstance(template, dict):
        return {k: render_value(v, variables) for k, v in template.items()}
    return template


def _query_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return _as_text(value)


def _with_query(url: str, params: Mapping[str, Any]) -> str:
    if not params:
        return url
    parts = urlsplit(url)
    extra = urlencode([(k, _query_value(v)) for k, v in params.items() if v is not None])
    query = f"{parts.query}&{extra}" if parts.query else extra
    return urlunsplit((parts.scheme, parts.netloc, parts.path, query, parts.fragment))


@dataclass
class PreparedRequest:
    method: str
    url: str
    headers: dict[str, str]
    body: Any = None
    has_body: bool = False
    missing_variables: list[str] = field(default_factory=list)
    secret_values: list[str] = field(default_factory=list)

    def content(self) -> bytes | None:
        if not self.has_body:
            return None
        return json.dumps(self.body, separators=(",", ":"), ensure_ascii=False).encode()


def prepare_request(
    spec: Mapping[str, Any],
    arguments: Mapping[str, Any],
    dynamic: Mapping[str, Any] | None = None,
    mapped: Mapping[str, Any] | None = None,
    secrets: Mapping[str, str] | None = None,
) -> PreparedRequest:
    """Build the outgoing request. Secret headers are taken from ``secrets`` by ``secret_ref``
    (or their write-only ``value`` in an unsaved editor test run)."""
    variables = Variables(arguments, dynamic, mapped)
    method = str(spec.get("method") or "POST").upper()
    url = render_text(str(spec.get("url") or ""), variables, url_encode=True)
    headers: dict[str, str] = {}
    secret_values: list[str] = []
    for header in spec.get("headers") or []:
        name = str(header["name"])
        if header.get("secret"):
            ref = header.get("secret_ref")
            value = (secrets or {}).get(str(ref)) if ref else None
            if value is None:
                value = header.get("value")
            if value is None:
                variables.missing.append(f"secret:{name}")
                continue
            secret_values.append(str(value))
            headers[name] = str(value)
        else:
            headers[name] = render_text(str(header.get("value") or ""), variables)
    template = spec.get("body_template")
    body: Any = None
    has_body = False
    if template is None:
        if method in QUERY_METHODS:
            url = _with_query(url, arguments)
        else:
            body, has_body = dict(arguments), True
    else:
        rendered = render_value(template, variables)
        if method in QUERY_METHODS:
            if isinstance(rendered, Mapping):
                url = _with_query(url, rendered)
        else:
            body, has_body = rendered, True
    if has_body and not any(k.lower() == "content-type" for k in headers):
        headers["Content-Type"] = "application/json"
    return PreparedRequest(
        method=method,
        url=url,
        headers=headers,
        body=body,
        has_body=has_body,
        missing_variables=list(variables.missing),
        secret_values=secret_values,
    )


def get_path(data: Any, path: str) -> tuple[bool, Any]:
    """Dot path with ``[n]`` indexes (``data.slots[0].time``); returns (found, value)."""
    node = data
    tokens = _PATH_TOKEN.findall(path.strip())
    if not tokens:
        return False, None
    for key, index in tokens:
        if index:
            i = int(index)
            if not isinstance(node, list) or i >= len(node):
                return False, None
            node = node[i]
        else:
            if isinstance(node, Mapping) and key in node:
                node = node[key]
            elif isinstance(node, list) and key.isdigit() and int(key) < len(node):
                node = node[int(key)]
            else:
                return False, None
    return True, node


def apply_mappings(body_text: str, mappings: list[Mapping[str, Any]]) -> tuple[dict[str, Any], list[str]]:
    """Mapped variables and the json paths that were not found."""
    if not mappings:
        return {}, []
    try:
        data = json.loads(body_text)
    except ValueError:
        return {}, [str(m["json_path"]) for m in mappings]
    mapped: dict[str, Any] = {}
    missing: list[str] = []
    for mapping in mappings:
        found, value = get_path(data, str(mapping["json_path"]))
        if found:
            mapped[str(mapping["variable_name"])] = value
        else:
            missing.append(str(mapping["json_path"]))
    return mapped, missing


def timeout_s(spec: Mapping[str, Any]) -> float:
    return int(spec.get("timeout_ms") or DEFAULT_TIMEOUT_MS) / 1000


def redirected(status: int, method: str, content: bytes | None) -> tuple[str, bytes | None]:
    """Method and body for the next hop: 303, and 301/302 after a method with a body, become GET."""
    if status == 303 or (status in (301, 302) and method not in QUERY_METHODS):
        return "GET", None
    return method, content


def blocked_error_code(reason: str) -> str:
    """Tool error code for a URL the guard refused (``url_guard.UrlNotAllowed.reason``)."""
    return "blocked_address" if reason in ("private_address", "https_required") else "connection_error"


async def read_capped(chunks: AsyncIterable[bytes]) -> tuple[bytes, bool]:
    """At most ``MAX_RESPONSE_BYTES`` of a body, and whether it was cut."""
    data = bytearray()
    async for chunk in chunks:
        data.extend(chunk)
        if len(data) > MAX_RESPONSE_BYTES:
            return bytes(data[:MAX_RESPONSE_BYTES]), True
    return bytes(data), False


def truncate(text: str, limit: int = MAX_LLM_PAYLOAD_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 15] + " ...[truncated]"


def success_payload(body_text: str) -> str:
    """What the agent receives for a successful call: compact JSON when the body is JSON."""
    try:
        data = json.loads(body_text)
    except ValueError:
        return truncate(body_text.strip())
    return truncate(json.dumps(data, separators=(",", ":"), ensure_ascii=False))


def error_payload(code: str, message: str, http_status: int | None = None) -> str:
    body: dict[str, Any] = {"error": code, "message": message}
    if http_status is not None:
        body["http_status"] = http_status
    return json.dumps(body, separators=(",", ":"))


def scrub(text: str, secrets: list[str]) -> str:
    for value in secrets:
        if value and len(value) >= 4:
            text = text.replace(value, "****")
    return text
