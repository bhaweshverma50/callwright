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


def needs_secrets(config: Mapping[str, Any]) -> bool:
    for spec in config.get("tools") or []:
        for header in (spec.get("config") or {}).get("headers") or []:
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
