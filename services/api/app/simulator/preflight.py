"""Pre-flight check before any simulation start (008 T050; FR-015, US2 scenario 2).

Reports the tools (HTTP tools and flow webhook nodes) without a mock response, the calls that
cannot be simulated with their reason, the number of runs and the estimated cost. The estimate
is the median charged cost of the agent's last 50 completed runs of the same mode, or a
fallback per mode when there is no history, times the run count (persona runs from a base call
add the brief extraction). Prices come from the same token prices the charges use.
"""

from __future__ import annotations

import statistics
from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.models import Agent
from app.llms.client import billable_cost, token_cost
from app.simulator.models import SimulationRun
from app.simulator.service import MAX_BATCH, MIN_BATCH, dataset_calls
from app.testing import calls as sim_calls
from app.testing.targets import resolve_target

HISTORY = 50
# Typical token use per run when the agent has no history (agent and caller sides).
FALLBACK_TOKENS = {"replay": (6_000, 600), "persona": (14_000, 1_400)}
EXTRACTION_TOKENS = (2_000, 250)


def tools_missing_mock(config: Mapping[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for tool in config.get("tools") or []:
        if not isinstance(tool, Mapping) or tool.get("type") != "http":
            continue
        if not str(tool.get("mock_response") or "").strip():
            out.append(
                {
                    "tool_id": tool.get("tool_id"),
                    "node_id": None,
                    "name": str(tool.get("name") or "tool"),
                    "kind": "tool",
                }
            )
    flow = config.get("flow")
    compiled = flow.get("compiled") if isinstance(flow, Mapping) else None
    nodes = compiled.get("nodes") if isinstance(compiled, Mapping) else None
    for node_id, node in (nodes or {}).items() if isinstance(nodes, Mapping) else []:
        if not isinstance(node, Mapping) or node.get("type") != "webhook":
            continue
        raw_spec = node.get("webhook")
        spec: Mapping[str, Any] = raw_spec if isinstance(raw_spec, Mapping) else {}
        if not str(spec.get("mock_response") or "").strip():
            out.append(
                {
                    "tool_id": None,
                    "node_id": str(node_id),
                    "name": str(node.get("label") or node_id),
                    "kind": "webhook_node",
                }
            )
    return out


def fallback_cost(mode: str, model: str) -> Decimal:
    inp, out = FALLBACK_TOKENS.get(mode, FALLBACK_TOKENS["replay"])
    return billable_cost(token_cost(model.partition("/")[2] or model, inp, out))


async def per_run_cost(session: AsyncSession, agent_id: str, mode: str, model: str) -> Decimal:
    rows = await session.execute(
        select(SimulationRun.cost_usd)
        .where(
            SimulationRun.agent_id == agent_id,
            SimulationRun.mode == mode,
            SimulationRun.status == "completed",
        )
        .where(SimulationRun.cost_usd.is_not(None))
        .order_by(SimulationRun.finished_at.desc())
        .limit(HISTORY)
    )
    history = [Decimal(c) for c in rows.scalars() if c is not None]
    if history:
        return Decimal(statistics.median(history))
    return fallback_cost(mode, model)


async def preflight(
    session: AsyncSession,
    agent: Agent,
    *,
    mode: str,
    target: Mapping[str, Any] | None,
    base_call_ids: Sequence[str] | None,
    dataset_id: str | None,
    simulator_model: str,
) -> dict[str, Any]:
    resolved = await resolve_target(session, agent, target, default="published")
    warnings: list[str] = []
    ids: list[str] = list(dict.fromkeys(base_call_ids or []))
    if dataset_id:
        ids, skipped = await dataset_calls(session, dataset_id, agent.id)
        if skipped:
            warnings.append(
                f"{skipped} call{'s' if skipped != 1 else ''} in the dataset can no longer be "
                "simulated and will be skipped."
            )
    calls = await sim_calls.load_calls(session, ids)
    invalid = []
    for call_id in ids:
        reason = sim_calls.call_problem(calls.get(call_id), agent.id)
        if reason:
            invalid.append({"call_id": call_id, "reason": reason})
    if any(i["reason"] == "wrong_agent" for i in invalid):
        warnings.append("Some calls belong to another agent. Narrow the selection to one agent.")
    bad = {i["call_id"] for i in invalid}
    run_count = len([c for c in ids if c not in bad]) if ids else (1 if mode == "persona" else 0)
    if len(ids) > 1 and not MIN_BATCH <= len(ids) <= MAX_BATCH:
        warnings.append(f"A batch takes {MIN_BATCH} to {MAX_BATCH} calls.")
    missing = tools_missing_mock(resolved.config)
    if missing:
        warnings.append(
            "Tools without a mock response answer with the recorded output when there is one, "
            "otherwise with a generated stand-in."
        )
    per_run = await per_run_cost(session, agent.id, mode, simulator_model)
    total = per_run * run_count
    if mode == "persona" and ids:
        total += (
            billable_cost(
                token_cost(simulator_model.partition("/")[2] or simulator_model, *EXTRACTION_TOKENS)
            )
            * run_count
        )
    return {
        "run_count": run_count,
        "tools_missing_mock": missing,
        "estimated_cost_usd": float(total.quantize(Decimal("0.000001"))),
        "invalid_calls": invalid,
        "warnings": warnings,
    }
