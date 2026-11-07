"""Per-call tool secrets (005 T046, research R3).

Fetched once at session start (``InternalApiClient.tool_secrets``) when the snapshot has secret
headers, and kept in memory for the call only; never logged. ``scrub`` removes secret values
from text before it is recorded in events or transcripts.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any


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


def scrub(text: str, values: Iterable[str]) -> str:
    for value in values:
        if value and len(value) >= 4:
            text = text.replace(value, "****")
    return text
