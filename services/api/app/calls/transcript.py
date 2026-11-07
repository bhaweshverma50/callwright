"""The stored transcript (``calls.transcript.items``) and the one reader of its items.

The worker writes items as it emits them (``services/voice-worker/worker/metrics.py`` and
``control.py``): messages carry ``role``, ``text``, ``turn_index``, ``started_ms`` and
``confidence``; tool calls ``name``, ``arguments``, ``ref`` and ``at_ms``; tool results ``name``,
``output``, ``is_error``, ``ref`` and ``duration_ms``; flow transitions ``from_node_id``,
``to_node_id`` and ``label``.

* ``parse`` reads them into messages, tool events and flow transitions (evaluators, analysis,
  simulations, issues); ``has_conversation`` is whether anyone said anything.
* ``flow_transitions`` falls back to the ``flow_transition`` events when the transcript has none.
* ``normalize_items`` maps them to the contract's ``CallTranscriptItem`` union for the call view:
  flow transitions and system markers dropped (the flow path is its own view), a stable id on
  every item, each tool result paired with its call (by ``ref``, else the latest call of the same
  tool).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.calls.models import Call, CallEvent


@dataclass(frozen=True)
class Message:
    """One spoken line. ``index`` is its position among messages (the judge's turn number)."""

    index: int
    role: Literal["agent", "user"]
    text: str
    turn_index: int | None = None
    started_ms: int | None = None


@dataclass(frozen=True)
class ToolEvent:
    name: str
    arguments: Mapping[str, Any] | None
    output: str | None
    is_error: bool
    ref: str | None = None
    after_message: int = -1  # index of the last message before the call (-1: before any)


@dataclass(frozen=True)
class FlowTransition:
    from_node_id: str | None
    to_node_id: str
    label: str | None = None


@dataclass
class Transcript:
    messages: list[Message] = field(default_factory=list)
    tools: list[ToolEvent] = field(default_factory=list)
    transitions: list[FlowTransition] = field(default_factory=list)


def stored_items(stored: Any) -> list[Mapping[str, Any]]:
    """The items of a stored transcript (``calls.transcript``; None or malformed reads as empty)."""
    transcript = stored if isinstance(stored, Mapping) else {}
    return [i for i in transcript.get("items") or [] if isinstance(i, Mapping)]


def items(call: Call) -> list[Mapping[str, Any]]:
    return stored_items(call.transcript)


def parse(items: Sequence[Mapping[str, Any]]) -> Transcript:
    """Spoken lines (empty ones dropped), tool calls paired with their results, flow transitions."""
    messages: list[Message] = []
    tools: list[ToolEvent] = []
    transitions: list[FlowTransition] = []
    pending: dict[str, dict[str, Any]] = {}
    for item in items:
        kind = item.get("type")
        if kind == "message":
            role = item.get("role")
            text = str(item.get("text") or "")
            if role not in ("agent", "user") or not text.strip():
                continue
            turn = item.get("turn_index")
            started = item.get("started_ms")
            messages.append(
                Message(
                    len(messages),
                    role,
                    text,
                    int(turn) if isinstance(turn, int) else None,
                    int(started) if isinstance(started, int | float) else None,
                )
            )
        elif kind == "tool_call":
            ref = str(item.get("ref") or f"anon{len(tools)}")
            args = item.get("arguments")
            pending[ref] = {
                "name": str(item.get("name") or "tool"),
                "arguments": args if isinstance(args, Mapping) else None,
                "after": len(messages) - 1,
            }
            tools.append(
                ToolEvent(
                    pending[ref]["name"], pending[ref]["arguments"], None, False, ref, len(messages) - 1
                )
            )
        elif kind == "tool_result":
            ref = str(item.get("ref") or "")
            for i in range(len(tools) - 1, -1, -1):
                if tools[i].ref == ref or (
                    not ref and tools[i].name == item.get("name") and tools[i].output is None
                ):
                    old = tools[i]
                    tools[i] = ToolEvent(
                        old.name,
                        old.arguments,
                        str(item.get("output") or ""),
                        bool(item.get("is_error")),
                        old.ref,
                        old.after_message,
                    )
                    break
        elif kind == "flow_transition" and item.get("to_node_id"):
            transitions.append(
                FlowTransition(
                    str(item["from_node_id"]) if item.get("from_node_id") else None,
                    str(item["to_node_id"]),
                    str(item["label"]) if item.get("label") else None,
                )
            )
    return Transcript(messages, tools, transitions)


def read(call: Call) -> Transcript:
    return parse(items(call))


def has_conversation(stored: Any) -> bool:
    """Whether a stored transcript has anything said: datasets, simulations and evaluations use
    only calls that do."""
    return bool(parse(stored_items(stored)).messages)


async def flow_transitions(session: AsyncSession, call: Call) -> list[FlowTransition]:
    """The flow path from the transcript, else from the call's ``flow_transition`` events."""
    transitions = read(call).transitions
    if transitions:
        return transitions
    rows = (
        await session.execute(
            select(CallEvent.payload)
            .where(CallEvent.call_id == call.id, CallEvent.type == "flow_transition")
            .order_by(CallEvent.seq)
        )
    ).scalars()
    return [
        FlowTransition(p.get("from_node_id"), str(p["to_node_id"]), p.get("label"))
        for p in rows
        if p.get("to_node_id")
    ]


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
