"""Build an ``EvalContext`` for one call (007 T008 input side).

Messages, tool events and flow transitions come from the finalised transcript (003
``finalize_transcript``); per-turn latency from ``turn`` events; the configuration from the
agent version the call ran (FR edge case: evaluators judge against that version, not the
current draft); the recording reference only when the recording is available.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.call_events.models import CallEvent
from app.call_events.service import version_config
from app.calls.models import Call
from app.evaluators.base import EvalContext, FlowTransition, Message, RecordingRef, ToolEvent, TurnLatency


def parse_transcript(
    items: list[Mapping[str, Any]],
) -> tuple[list[Message], list[ToolEvent], list[FlowTransition]]:
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
    return messages, tools, transitions


async def build_context(
    session: AsyncSession, call: Call, *, run_id: str = "", recordings_bucket: str | None = None
) -> EvalContext:
    config: Mapping[str, Any] = await version_config(session, call.agent_version_id) or {}
    items = list((call.transcript or {}).get("items") or [])
    messages, tools, transitions = parse_transcript(items)
    turn_rows = (
        await session.execute(
            select(CallEvent.turn_index, CallEvent.e2e_ms)
            .where(CallEvent.call_id == call.id, CallEvent.type == "turn")
            .order_by(CallEvent.seq)
        )
    ).all()
    latencies = [
        TurnLatency(int(t), int(e)) for t, e in turn_rows if t is not None and t > 0 and e is not None
    ]
    if not transitions:
        rows = (
            await session.execute(
                select(CallEvent.payload)
                .where(CallEvent.call_id == call.id, CallEvent.type == "flow_transition")
                .order_by(CallEvent.seq)
            )
        ).scalars()
        for payload in rows:
            if payload.get("to_node_id"):
                transitions.append(
                    FlowTransition(
                        payload.get("from_node_id"), str(payload["to_node_id"]), payload.get("label")
                    )
                )
    recording = None
    if call.recording_enabled and call.recording_status == "available" and call.recording_key:
        recording = RecordingRef(call.recording_key, recordings_bucket)
    agent_type = str(config.get("type") or "single_prompt")
    return EvalContext(
        call_id=call.id,
        workspace_id=call.workspace_id,
        agent_id=call.agent_id,
        agent_type="flow" if agent_type == "flow" else "single_prompt",
        origin=call.origin,
        ended_at=call.ended_at,
        disconnect_reason=call.disconnect_reason,
        config=config,
        messages=messages,
        tools=tools,
        transitions=transitions,
        latencies=latencies,
        recording=recording,
        run_id=run_id,
    )
