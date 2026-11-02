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
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.calls.models import Call
from app.core.ids import is_valid_id, new_id

REASONS = ("not_found", "wrong_agent", "simulated_call", "not_completed", "unavailable")
REASON_TEXT = {
    "not_found": "No call with that id exists in this workspace.",
    "wrong_agent": "The call belongs to another agent.",
    "simulated_call": "Simulated calls cannot be used.",
    "not_completed": "The call has not completed.",
    "unavailable": "The call's transcript is no longer available.",
}


def items_of(call: Call) -> list[Mapping[str, Any]]:
    transcript = call.transcript if isinstance(call.transcript, Mapping) else {}
    return [i for i in transcript.get("items") or [] if isinstance(i, Mapping)]


def has_conversation(call: Call) -> bool:
    return any(i.get("type") == "message" and str(i.get("text") or "").strip() for i in items_of(call))


def call_problem(call: Call | None, agent_id: str) -> str | None:
    if call is None:
        return "not_found"
    if call.agent_id != agent_id:
        return "wrong_agent"
    if call.origin == "simulation":
        return "simulated_call"
    if call.status != "completed":
        return "not_completed"
    if not has_conversation(call):
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
    start_speaker: str = "agent"
    caller_turns: list[str] = field(default_factory=list)
    recorded_tool_outputs: list[dict[str, str]] = field(default_factory=list)
    node_path: list[str] = field(default_factory=list)


def replay_material(items: Sequence[Mapping[str, Any]]) -> ReplayMaterial:
    out = ReplayMaterial()
    first = next((i for i in items if i.get("type") == "message" and str(i.get("text") or "").strip()), None)
    out.start_speaker = "user" if first is not None and first.get("role") == "user" else "agent"
    last_role: str | None = None
    names: dict[str, str] = {}
    for item in items:
        kind = item.get("type")
        if kind == "message":
            text = str(item.get("text") or "").strip()
            role = item.get("role")
            if not text:
                continue
            if role == "user":
                if last_role == "user" and out.caller_turns:
                    out.caller_turns[-1] = f"{out.caller_turns[-1]} {text}"
                else:
                    out.caller_turns.append(text)
            last_role = str(role)
        elif kind == "tool_call":
            if item.get("ref"):
                names[str(item["ref"])] = str(item.get("name") or "")
        elif kind == "tool_result":
            name = str(item.get("name") or names.get(str(item.get("ref") or ""), "") or "")
            if name:
                out.recorded_tool_outputs.append({"name": name, "output": str(item.get("output") or "")})
        elif kind == "flow_transition" and item.get("to_node_id"):
            out.node_path.append(str(item["to_node_id"]))
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
