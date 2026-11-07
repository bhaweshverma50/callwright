"""Latency budget gate on fakes (Principle II): p50 <= 800 ms, p95 <= 1,500 ms, <= 10% drift."""

from __future__ import annotations

import json

from tests.harness.bench.benchmark import (
    DEFAULT_BASELINE,
    BenchReport,
    gate,
    percentile,
    run_benchmark,
)


async def test_benchmark_meets_budget_and_baseline() -> None:
    report = await run_benchmark()
    assert report.calls == 20 and report.turns == 120
    baseline = json.loads(DEFAULT_BASELINE.read_text())
    assert gate(report, baseline) == []


async def test_benchmark_is_deterministic() -> None:
    first = await run_benchmark()
    second = await run_benchmark()
    assert first == second


def _report(p50: float, p95: float) -> BenchReport:
    return BenchReport(20, 120, p50, p95, p95, 160, 400, 320, 130)


def test_gate_flags_budget_and_regression() -> None:
    baseline = {"e2e_p50_ms": 600, "e2e_p95_ms": 1000}
    assert gate(_report(600, 1000), baseline) == []
    assert gate(_report(660, 1100), baseline) == []  # exactly +10% passes
    failures = gate(_report(700, 1000), baseline)
    assert len(failures) == 1 and "e2e_p50_ms" in failures[0]
    failures = gate(_report(900, 1600), None)
    assert len(failures) == 2
    # The R4 pause call set gates on p95 only.
    assert gate(_report(900, 1400), None, p50_budget=False) == []


def test_percentile_nearest_rank() -> None:
    values = list(range(1, 101))
    assert percentile(values, 50) == 50
    assert percentile(values, 95) == 95
    assert percentile([5.0], 95) == 5.0
