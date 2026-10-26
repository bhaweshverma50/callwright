"""Per-call tool secrets (005 T046, research R3).

Fetched once at session start from ``GET /v1/internal/calls/{call_id}/tool-secrets`` and kept in
memory for the call only; never logged. ``scrub`` removes secret values from text before it is
recorded in events or transcripts.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping
from typing import Any

import httpx

log = logging.getLogger(__name__)


def _header_lists(config: Mapping[str, Any]) -> list[Any]:
    lists = [(spec.get("config") or {}).get("headers") or [] for spec in config.get("tools") or []]
    raw_flow = config.get("flow")
    flow: Mapping[str, Any] = raw_flow if isinstance(raw_flow, Mapping) else {}
    raw_compiled = flow.get("compiled")
    compiled: Mapping[str, Any] = raw_compiled if isinstance(raw_compiled, Mapping) else {}
    for node in (compiled.get("nodes") or {}).values():  # 004: node tools and webhook nodes
        for spec in node.get("tools") or []:
            lists.append((spec.get("config") or {}).get("headers") or [])
        lists.append(((node.get("webhook") or {}).get("request") or {}).get("headers") or [])
    return lists


def needs_secrets(config: Mapping[str, Any]) -> bool:
    for headers in _header_lists(config):
        for header in headers:
            if header.get("secret") and header.get("secret_ref"):
                return True
    return False


async def fetch(
    client: httpx.AsyncClient, base_url: str, service_token: str, call_id: str
) -> dict[str, str]:
    """The secret map, or an empty map when the API cannot provide it (tools then answer
    ``secret_unavailable`` and the call goes on)."""
    try:
        response = await client.get(
            f"{base_url.rstrip('/')}/calls/{call_id}/tool-secrets",
            headers={"Authorization": f"Bearer {service_token}"},
        )
    except httpx.HTTPError as exc:
        log.warning("tool secrets unavailable for %s: %s", call_id, type(exc).__name__)
        return {}
    if response.status_code != 200:
        log.warning("tool secrets unavailable for %s: HTTP %s", call_id, response.status_code)
        return {}
    secrets = response.json().get("secrets") or {}
    return {str(k): str(v) for k, v in secrets.items()}


def scrub(text: str, values: Iterable[str]) -> str:
    for value in values:
        if value and len(value) >= 4:
            text = text.replace(value, "****")
    return text
