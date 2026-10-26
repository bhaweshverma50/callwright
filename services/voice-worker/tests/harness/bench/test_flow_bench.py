"""004 latency gates (T051, T052, T072): engine overhead per move and flow turn latency against
the single-prompt baseline. Run with every worker test, so changes under worker/flow are gated."""

from __future__ import annotations

from tests.harness.bench import bench_flow_engine, bench_flow_turn_latency


async def test_flow_engine_overhead_gate() -> None:
    report = await bench_flow_engine.run(iterations=200)
    assert bench_flow_engine.gate(report) == [], report


async def test_flow_turn_latency_gate() -> None:
    report = await bench_flow_turn_latency.run(turns=6)
    assert bench_flow_turn_latency.gate(report) == [], report
