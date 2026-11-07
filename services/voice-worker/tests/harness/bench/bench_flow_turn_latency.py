"""Turn latency of flow agents against the single-prompt baseline (004 T052, SC-004).

Runs the real ``AgentSession`` in text mode with a fake model whose first token takes
``LLM_TTFT_S`` (the default stack's measured time to first token): the same caller turns go to
a single-prompt agent and to a flow agent, turns without a node move and moves into a node with
a fixed entry line. Gates: p50 at most 800 ms, p95 at most 1500 ms, and turns without a move no
more than 5% slower than the baseline.

``uv run python -m tests.harness.bench.bench_flow_turn_latency``
"""

from __future__ import annotations

import asyncio
import copy
import json
import sys
import time
from typing import Any

from tests.flow_support import FlowScript, RecordingControl, Rule, compiled_config, flow_llm
from tests.harness.bench.benchmark import percentile
from tests.harness.runner import build_runtime, load_agent_config
from worker.adapters.registry import AdapterRegistry
from worker.flow.runtime import CallwrightFlowRunner
from worker.pipeline import build_agent, plan_session
from worker.tools.registry import build_call_tools

LLM_TTFT_S = 0.35
TURNS = 12
P50_MS, P95_MS, REGRESSION = 800.0, 1500.0, 1.05


async def _timed_turns(agent: Any, script: FlowScript, lines: list[str]) -> list[float]:
    from livekit.agents import AgentSession, llm

    llm.LLM.prewarm = lambda self, **_: None  # type: ignore[method-assign]
    out: list[float] = []
    async with AgentSession(llm=flow_llm(script), vad=None) as session:
        await session.start(agent)
        for line in lines:
            started = time.perf_counter()
            await session.run(user_input=line)
            out.append((time.perf_counter() - started) * 1000)
    return out


async def run(turns: int = TURNS) -> dict[str, Any]:
    script = FlowScript(llm_delay_s=LLM_TTFT_S)
    baseline_rt = build_runtime(load_agent_config(), {})
    baseline_plan = plan_session(baseline_rt, AdapterRegistry())
    baseline = await _timed_turns(
        build_agent(
            baseline_plan,
            baseline_rt,
            None,  # type: ignore[arg-type]
            build_call_tools(baseline_rt, None),  # type: ignore[arg-type]
        ),
        script,
        ["Hello"] * turns,
    )

    config = copy.deepcopy(compiled_config("overrides_context"))
    rt = build_runtime(config, {})
    flows = CallwrightFlowRunner()
    plan = plan_session(rt, AdapterRegistry(), flows)
    control = RecordingControl()
    agent = build_agent(plan, rt, control, build_call_tools(rt, control), flows=flows)
    flow = await _timed_turns(agent, script, ["Hello"] * turns)

    moves: list[float] = []
    move_script = FlowScript(
        rules=[Rule(match="spanish", tool="route_to_spanish")], llm_delay_s=LLM_TTFT_S
    )
    for _ in range(max(3, turns // 3)):
        control = RecordingControl()
        agent = build_agent(plan, rt, control, build_call_tools(rt, control), flows=flows)
        moves += await _timed_turns(agent, move_script, ["Spanish please"])

    def stats(values: list[float]) -> dict[str, float]:
        return {
            "p50_ms": round(percentile(values, 50), 1),
            "p95_ms": round(percentile(values, 95), 1),
        }

    return {
        "ttft_ms": LLM_TTFT_S * 1000,
        "baseline": stats(baseline),
        "flow_no_move": stats(flow),
        "flow_move_entry_line": stats(moves),
    }


def gate(report: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    for key in ("flow_no_move", "flow_move_entry_line"):
        if report[key]["p50_ms"] > P50_MS:
            problems.append(f"{key} p50 {report[key]['p50_ms']} ms > {P50_MS}")
        if report[key]["p95_ms"] > P95_MS:
            problems.append(f"{key} p95 {report[key]['p95_ms']} ms > {P95_MS}")
    if report["flow_no_move"]["p50_ms"] > report["baseline"]["p50_ms"] * REGRESSION:
        problems.append("turns without a move are more than 5% slower than single-prompt turns")
    return problems


def main() -> int:
    report = asyncio.run(run())
    print(json.dumps(report, indent=2))
    return 1 if gate(report) else 0


if __name__ == "__main__":
    sys.exit(main())
