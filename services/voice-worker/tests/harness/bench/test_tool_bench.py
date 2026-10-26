"""005 latency gates (T021, T041) on in-process stubs; CI runs these with the offline harness."""

from __future__ import annotations

from tests.harness.bench import bench_http_tool, bench_tool_dispatch


async def test_tool_dispatch_overhead_gate() -> None:
    report = await bench_tool_dispatch.run(iterations=200)
    assert bench_tool_dispatch.gate(report) == [], report


async def test_http_tool_gate() -> None:
    report = await bench_http_tool.run(iterations=200, slow_runs=2, slow_ms=900)
    assert bench_http_tool.gate(report) == [], report


async def test_call_set_with_tools_does_not_regress() -> None:
    import json

    from tests.harness.bench import bench_call_set_tools
    from tests.harness.bench.benchmark import DEFAULT_BASELINE

    plain, with_tools = await bench_call_set_tools.run()
    assert bench_call_set_tools.gate(with_tools, json.loads(DEFAULT_BASELINE.read_text())) == []
    assert with_tools.e2e_p95_ms <= plain.e2e_p95_ms * 1.05
