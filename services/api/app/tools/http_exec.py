"""Editor test runs of HTTP tools (T043, research R4, R5).

``run(spec, ...)`` prepares the request and sends it with the shared ``http_core`` (the same
guarded loop the worker runs on calls), applies the response mappings and returns the
``TestRunResult`` body with secret header values masked.
"""

from __future__ import annotations

import time
from collections.abc import Mapping
from typing import Any

import httpx
from callwright_contract import http_core, url_guard

from app.core.secrets import mask_secret


def _masked_headers(prepared: http_core.PreparedRequest, spec: Mapping[str, Any]) -> dict[str, str]:
    secret_names = {str(h["name"]).lower() for h in spec.get("headers") or [] if h.get("secret")}
    return {k: (mask_secret(v) if k.lower() in secret_names else v) for k, v in prepared.headers.items()}


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
        message = http_core.missing_message(prepared.missing_variables)
        outcome = http_core.Outcome("missing_variable", message, message)
    else:
        outcome = await http_core.execute(
            client, prepared, http_core.timeout_s(spec), allow_http=allow_http, resolver=resolver
        )
    mapped: dict[str, Any] = {}
    missing_paths: list[str] = []
    if not outcome.is_error:
        mapped, missing_paths = http_core.apply_mappings(
            outcome.body_text or "", list(spec.get("response_mappings") or [])
        )
    secrets_used = prepared.secret_values
    body = outcome.body_text
    return {
        "is_error": outcome.is_error,
        "error_code": outcome.error_code,
        "error_message": outcome.detail or None,
        "request": {
            "method": prepared.method,
            "url": http_core.scrub(prepared.url, secrets_used),
            "headers": _masked_headers(prepared, spec),
            "body": prepared.body,
        },
        "http_status": outcome.http_status,
        "duration_ms": round((time.perf_counter() - started) * 1000),
        "response_body": http_core.scrub(body, secrets_used) if body is not None else None,
        "mapped_variables": mapped,
        "missing_paths": missing_paths,
        "llm_payload": http_core.scrub(outcome.llm_payload(), secrets_used),
    }
