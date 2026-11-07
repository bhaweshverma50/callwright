"""Editor test runs of HTTP tools (T043, research R4, R5).

``run(spec, ...)`` prepares the request with the shared ``http_core``, checks every hop with the
shared URL guard, connects to the vetted IP with the original Host and TLS name, follows the
core's redirect rules, reads at most 64 KB, applies the response mappings and returns the
``TestRunResult`` body with secret header values masked.
"""

from __future__ import annotations

import time
from collections.abc import Mapping
from typing import Any
from urllib.parse import urljoin

import httpx
from callwright_contract import http_core, url_guard

from app.core.secrets import mask_secret


def _masked_headers(prepared: http_core.PreparedRequest, spec: Mapping[str, Any]) -> dict[str, str]:
    secret_names = {str(h["name"]).lower() for h in spec.get("headers") or [] if h.get("secret")}
    return {k: (mask_secret(v) if k.lower() in secret_names else v) for k, v in prepared.headers.items()}


async def _send(
    client: httpx.AsyncClient,
    method: str,
    checked: url_guard.CheckedUrl,
    *,
    content: bytes | None,
    headers: Mapping[str, str],
    timeout_s: float,
) -> httpx.Response:
    request_headers = {**headers, "Host": url_guard.host_header(checked)}
    extensions: dict[str, Any] = {"timeout": httpx.Timeout(timeout_s).as_dict()}
    if checked.scheme == "https":
        extensions["sni_hostname"] = checked.host
    request = client.build_request(
        method,
        url_guard.pinned_url(checked, checked.addresses[0]),
        content=content,
        headers=request_headers,
        extensions=extensions,
    )
    return await client.send(request, stream=True, follow_redirects=False)


def _result(
    started: float,
    prepared: http_core.PreparedRequest | None,
    spec: Mapping[str, Any],
    *,
    is_error: bool,
    error_code: str | None = None,
    error_message: str | None = None,
    http_status: int | None = None,
    body_text: str | None = None,
    mapped: dict[str, Any] | None = None,
    missing_paths: list[str] | None = None,
    llm_payload: str = "",
) -> dict[str, Any]:
    secrets = prepared.secret_values if prepared else []
    request: dict[str, Any] = {}
    if prepared is not None:
        request = {
            "method": prepared.method,
            "url": http_core.scrub(prepared.url, secrets),
            "headers": _masked_headers(prepared, spec),
            "body": prepared.body,
        }
    return {
        "is_error": is_error,
        "error_code": error_code,
        "error_message": error_message,
        "request": request,
        "http_status": http_status,
        "duration_ms": round((time.perf_counter() - started) * 1000),
        "response_body": http_core.scrub(body_text, secrets) if body_text is not None else None,
        "mapped_variables": mapped or {},
        "missing_paths": missing_paths or [],
        "llm_payload": http_core.scrub(llm_payload, secrets),
    }


async def run(
    spec: Mapping[str, Any],
    arguments: Mapping[str, Any],
    dynamic_variables: Mapping[str, Any],
    *,
    client: httpx.AsyncClient,
    secrets: Mapping[str, str] | None = None,
    allow_http: bool = False,
    resolver: url_guard.Resolver | None = None,
) -> dict[str, Any]:
    started = time.perf_counter()
    prepared = http_core.prepare_request(spec, arguments, dynamic_variables, None, secrets)
    if prepared.missing_variables:
        names = ", ".join(prepared.missing_variables)
        message = f"No value for {names}."
        return _result(
            started,
            prepared,
            spec,
            is_error=True,
            error_code="missing_variable",
            error_message=message,
            llm_payload=http_core.error_payload("missing_variable", message),
        )
    timeout_s = http_core.timeout_s(spec)
    deadline = started + timeout_s
    method, url, content = prepared.method, prepared.url, prepared.content()
    try:
        for hop in range(http_core.MAX_REDIRECTS + 1):
            checked = await url_guard.check_url(url, allow_http=allow_http, resolver=resolver)
            remaining = max(0.05, deadline - time.perf_counter())
            response = await _send(
                client, method, checked, content=content, headers=prepared.headers, timeout_s=remaining
            )
            location = response.headers.get("location")
            if (
                response.status_code in http_core.REDIRECT_STATUSES
                and location
                and hop < http_core.MAX_REDIRECTS
            ):
                await response.aclose()
                url = urljoin(url, location)
                method, content = http_core.redirected(response.status_code, method, content)
                continue
            try:
                data, too_large = await http_core.read_capped(response.aiter_bytes())
            finally:
                await response.aclose()
            break
    except url_guard.UrlNotAllowed as exc:
        code = http_core.blocked_error_code(exc.reason)
        return _result(
            started,
            prepared,
            spec,
            is_error=True,
            error_code=code,
            error_message=exc.detail,
            llm_payload=http_core.error_payload(code, "The request could not be sent."),
        )
    except httpx.TimeoutException:
        message = f"No response within {timeout_s:g} s."
        return _result(
            started,
            prepared,
            spec,
            is_error=True,
            error_code="timeout",
            error_message=message,
            llm_payload=http_core.error_payload("timeout", message),
        )
    except httpx.HTTPError as exc:
        return _result(
            started,
            prepared,
            spec,
            is_error=True,
            error_code="connection_error",
            error_message=f"Could not connect: {type(exc).__name__}.",
            llm_payload=http_core.error_payload("connection_error", "The service could not be reached."),
        )
    body_text = data.decode("utf-8", errors="replace")
    status = response.status_code
    if too_large:
        message = "The response is larger than 64 KB."
        return _result(
            started,
            prepared,
            spec,
            is_error=True,
            error_code="response_too_large",
            error_message=message,
            http_status=status,
            body_text=body_text,
            llm_payload=http_core.error_payload("response_too_large", message, status),
        )
    if status >= 400:
        message = f"The service answered HTTP {status}."
        return _result(
            started,
            prepared,
            spec,
            is_error=True,
            error_code="http_status",
            error_message=message,
            http_status=status,
            body_text=body_text,
            llm_payload=http_core.error_payload("http_status", message, status),
        )
    mapped, missing = http_core.apply_mappings(body_text, list(spec.get("response_mappings") or []))
    return _result(
        started,
        prepared,
        spec,
        is_error=False,
        http_status=status,
        body_text=body_text,
        mapped=mapped,
        missing_paths=missing,
        llm_payload=http_core.success_payload(body_text),
    )
