"""Transcript read model and plain-text copy (006 T028, FR-009, FR-010).

The worker stores items as it emits them (``services/voice-worker/worker/metrics.py``):
messages carry ``started_ms`` and ``confidence``, tool items ``name``, ``ref`` and ``at_ms``.
``normalize_items`` maps them to the contract's ``CallTranscriptItem`` union, drops flow
transitions and system markers (the flow path is its own view), gives every item a stable id
and pairs each tool result with its call (by ``ref``, else the latest call of the same tool).
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from typing import Any


def _int(value: Any) -> int | None:
    return int(value) if isinstance(value, int | float) and not isinstance(value, bool) else None


def normalize_items(raw: Iterable[Mapping[str, Any]] | None) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    by_ref: dict[str, str] = {}
    latest_by_tool: dict[str, str] = {}
    last_offset = 0
    for index, item in enumerate(raw or []):
        kind = item.get("type")
        item_id = f"ti_{index:04d}"
        offset = _int(item.get("started_ms"))
        if offset is None:
            offset = _int(item.get("at_ms"))
        offset = max(last_offset, offset) if offset is not None else last_offset
        if kind == "message":
            role = "user" if item.get("role") == "user" else "agent"
            confidence = item.get("confidence") if role == "user" else None
            items.append(
                {
                    "id": item_id,
                    "type": "message",
                    "role": role,
                    "text": str(item.get("text") or ""),
                    "interrupted": bool(item.get("interrupted")),
                    "stt_confidence": float(confidence) if isinstance(confidence, int | float) else None,
                    "offset_ms": offset,
                    "turn_index": _int(item.get("turn_index")) if role == "agent" else None,
                }
            )
        elif kind == "tool_call":
            name = str(item.get("name") or "tool")
            arguments = item.get("arguments")
            items.append(
                {
                    "id": item_id,
                    "type": "tool_call",
                    "tool_name": name,
                    "arguments": dict(arguments) if isinstance(arguments, Mapping) else {},
                    "offset_ms": offset,
                    "turn_index": _int(item.get("turn_index")),
                }
            )
            if item.get("ref"):
                by_ref[str(item["ref"])] = item_id
            latest_by_tool[name] = item_id
        elif kind == "tool_result":
            name = str(item.get("name") or "tool")
            call_id = by_ref.get(str(item.get("ref"))) if item.get("ref") else None
            items.append(
                {
                    "id": item_id,
                    "type": "tool_result",
                    "tool_call_id": call_id or latest_by_tool.get(name, ""),
                    "tool_name": name,
                    "output": str(item.get("output") or ""),
                    "is_error": bool(item.get("is_error")),
                    "duration_ms": _int(item.get("duration_ms")),
                    "offset_ms": offset,
                }
            )
        else:
            continue
        last_offset = offset
    return items


def transcript_text(items: Iterable[Mapping[str, Any]]) -> str:
    lines: list[str] = []
    for item in items:
        if item["type"] == "message":
            speaker = "Caller" if item["role"] == "user" else "Agent"
            lines.append(f"{speaker}: {item['text']}")
        elif item["type"] == "tool_call":
            lines.append(
                f"[Tool call: {item['tool_name']}({json.dumps(item['arguments'], ensure_ascii=False)})]"
            )
        elif item["type"] == "tool_result":
            kind = "Tool error" if item["is_error"] else "Tool result"
            lines.append(f"[{kind}: {item['tool_name']} -> {item['output']}]")
    return "\n".join(lines)
