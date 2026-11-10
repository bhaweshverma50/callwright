"""Base calls and simulated calls (008; research R2, R5, FR-016, FR-018, FR-026).

* ``call_problem``: why a call cannot be a simulation base or a dataset item, checked in the
  data-model order: ``not_found``, ``wrong_agent``, ``simulated_call``, ``not_completed``,
  ``unavailable`` (transcript purged or empty).
* ``replay_material``: the caller turns (consecutive caller fragments merged), the start
  speaker, the recorded tool outputs in call order and the original flow node path.
* ``create_output_call``: the simulated call row, ``origin = simulation``, created when the
  runner starts. It goes through the post-call pipeline like a live call but is never priced,
  charged as a call or sent to customer webhooks.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.calls import transcript
from app.calls.models import Call
from app.calls.origins import policy
from app.core.ids import is_valid_id, new_id

REASON_TEXT = {
    "not_found": "No call with that id exists in this workspace.",
    "wrong_agent": "The call belongs to another agent.",
    "simulated_call": "Simulated calls cannot be used.",
    "not_completed": "The call has not completed.",
    "unavailable": "The call's transcript is no longer available.",
}


def call_problem(call: Call | None, agent_id: str) -> str | None:
    if call is None:
        return "not_found"
    if call.agent_id != agent_id:
        return "wrong_agent"
    if not policy(call.origin).has_real_audio:
        return "simulated_call"
    if call.status != "completed":
        return "not_completed"
    if not transcript.has_conversation(call.transcript):
        return "unavailable"
    return None


async def load_calls(session: AsyncSession, call_ids: Sequence[str]) -> dict[str, Call]:
    valid = [c for c in dict.fromkeys(call_ids) if is_valid_id(c, "call")]
    if not valid:
        return {}
    rows = await session.execute(select(Call).where(Call.id.in_(valid)))
    return {c.id: c for c in rows.scalars()}


@dataclass
class ReplayMaterial:
    start_speaker: Literal["agent", "user"] = "agent"
    caller_turns: list[str] = field(default_factory=list)
    recorded_tool_outputs: list[dict[str, str]] = field(default_factory=list)
    node_path: list[str] = field(default_factory=list)


def replay_material(call: Call) -> ReplayMaterial:
    parsed = transcript.read(call)
    out = ReplayMaterial()
    if parsed.messages and parsed.messages[0].role == "user":
        out.start_speaker = "user"
    last_role: str | None = None
    for message in parsed.messages:
        text = message.text.strip()
        if message.role == "user":
            if last_role == "user" and out.caller_turns:
                out.caller_turns[-1] = f"{out.caller_turns[-1]} {text}"
            else:
                out.caller_turns.append(text)
        last_role = message.role
    out.recorded_tool_outputs = [
        {"name": t.name, "output": t.output} for t in parsed.tools if t.output is not None
    ]
    out.node_path = [t.to_node_id for t in parsed.transitions]
    return out


def default_variables(config: Mapping[str, Any]) -> dict[str, str]:
    return {
        str(v["name"]): str(v.get("default") or "")
        for v in config.get("dynamic_variables") or []
        if isinstance(v, Mapping) and v.get("name")
    }


def run_variables(
    config: Mapping[str, Any], base: Call | None, given: Mapping[str, str] | None
) -> dict[str, str]:
    """Base call values, else the request's, over the agent's defaults (spec edge cases)."""
    values = default_variables(config)
    if base is not None:
        values.update({str(k): str(v) for k, v in (base.dynamic_variables or {}).items()})
    elif given:
        values.update({str(k): str(v) for k, v in given.items()})
    return values


def create_output_call(
    session: AsyncSession,
    *,
    workspace_id: str,
    agent_id: str,
    agent_version_id: str | None,
    simulation_run_id: str,
    base: Call | None,
    variables: Mapping[str, str],
    now: datetime | None = None,
) -> Call:
    call = Call(
        id=new_id("call"),
        workspace_id=workspace_id,
        agent_id=agent_id,
        agent_version_id=agent_version_id,
        origin="simulation",
        simulation_run_id=simulation_run_id,
        channel=base.channel if base is not None else "web",
        direction=base.direction if base is not None else "inbound",
        is_test=False,
        status="queued",
        dynamic_variables=dict(variables),
        missing_variables=[],
        ignored_overrides=[],
        metadata_={"simulation_run_id": simulation_run_id},
        created_at=now or datetime.now(UTC),
        usage={},
        usage_seq=0,
        recording_enabled=False,
        recording_setting_source="workspace",
        recording_status="not_recorded",
        pipeline_status="not_started",
        pipeline_warnings=[],
    )
    session.add(call)
    return call
