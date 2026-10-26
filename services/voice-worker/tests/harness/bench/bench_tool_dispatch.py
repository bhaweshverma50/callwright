"""Tool dispatch overhead benchmark (005 T021, Principle II).

Times the dispatch path (argument check, context, event recording, timing) around end_call,
press_digit (simulated, no waits) and a 0 ms in-process HTTP stub, 500 iterations each, and
gates p95 overhead at 50 ms.  ``uv run python -m tests.harness.bench.bench_tool_dispatch``
"""

from __future__ import annotations

import asyncio
import json
import sys
from typing import Any

import httpx

from tests.harness.bench.benchmark import percentile
from tests.unit.tool_support import http_spec, make, tool

GATE_P95_MS = 50.0


def _overheads(h: Any) -> list[float]:
    return [float(e["dispatch_overhead_ms"]) for e in h.events()]


async def run(iterations: int = 500) -> dict[str, dict[str, float]]:
    report: dict[str, dict[str, float]] = {}
    end = make([tool("end_call", "end_call")])
    for _ in range(iterations):
        await end.tools.dispatch("end_call", {})
    press = make([tool("press_digit", "press")], simulation=True)
    for _ in range(iterations):
        await press.tools.dispatch("press", {"digits": "1"})
    stub = make([http_spec()], handler=lambda r: httpx.Response(200, json={"ok": True}))
    for _ in range(iterations):
        await stub.tools.dispatch("check_availability", {"date": "2026-10-27"})
    for name, h in (("end_call", end), ("press_digit", press), ("http_stub_0ms", stub)):
        values = _overheads(h)
        durations = [float(e["duration_ms"]) for e in h.events()]
        report[name] = {
            "overhead_p50_ms": percentile(values, 50),
            "overhead_p95_ms": percentile(values, 95),
            "duration_p95_ms": percentile(durations, 95),
        }
        await h.tools.aclose()
    return report


def gate(report: dict[str, dict[str, float]]) -> list[str]:
    return [
        f"{name}: p95 overhead {r['overhead_p95_ms']} ms > {GATE_P95_MS} ms"
        for name, r in report.items()
        if r["overhead_p95_ms"] > GATE_P95_MS
    ]


if __name__ == "__main__":
    result = asyncio.run(run())
    print(json.dumps(result, indent=2))
    sys.exit(1 if gate(result) else 0)
