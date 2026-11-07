"""005 latency gates (T021, T041) on in-process stubs; CI runs these with the offline harness."""

from __future__ import annotations

from tests.harness.bench import bench_http_tool, bench_tool_dispatch


async def test_tool_dispatch_overhead_gate() -> None:
    report = await bench_tool_dispatch.run(iterations=200)
    assert bench_tool_dispatch.gate(report) == [], report


async def test_http_tool_gate() -> None:
    report = await bench_http_tool.run(iterations=200, slow_runs=2, slow_ms=900)
    assert bench_http_tool.gate(report) == [], report
