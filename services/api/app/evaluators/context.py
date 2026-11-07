"""Build an ``EvalContext`` for one call (007 T008 input side).

Messages, tool events and flow transitions come from the finalised transcript (003
``finalize_transcript``); per-turn latency from ``turn`` events; the configuration from the
agent version the call ran (FR edge case: evaluators judge against that version, not the
current draft; a simulated call against its run's snapshot); the recording reference only when
the recording is available.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.calls import transcript
from app.calls.lookups import config_for
from app.calls.models import Call, CallEvent
from app.evaluators.base import EvalContext, RecordingRef, TurnLatency


async def build_context(
    session: AsyncSession, call: Call, *, run_id: str = "", recordings_bucket: str | None = None
) -> EvalContext:
    config: Mapping[str, Any] = await config_for(session, call) or {}
    parsed = transcript.read(call)
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
        messages=parsed.messages,
        tools=parsed.tools,
        transitions=await transcript.flow_transitions(session, call),
        latencies=latencies,
        recording=recording,
        run_id=run_id,
    )
