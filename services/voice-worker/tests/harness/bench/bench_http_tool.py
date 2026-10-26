"""HTTP tool path benchmark (005 T041, Principle II).

1. Stub answering in 0 ms: dispatch plus request handling overhead p95 <= 50 ms.
2. Stub answering in 1,500 ms with nothing said yet: the waiting line starts within 450 ms of
   the call and is spoken exactly once.
``uv run python -m tests.harness.bench.bench_http_tool``
"""

from __future__ import annotations

import asyncio
import json
import sys
import time

import httpx

from tests.harness.bench.benchmark import percentile
from tests.unit.tool_support import http_spec, make

GATE_OVERHEAD_P95_MS = 50.0
GATE_WAITING_LINE_MS = 450.0


async def run(iterations: int = 500, slow_runs: int = 3, slow_ms: float = 1500) -> dict[str, float]:
    fast = make([http_spec()], handler=lambda r: httpx.Response(200, json={"slots": ["09:30"]}))
    for _ in range(iterations):
        await fast.tools.dispatch("check_availability", {"date": "2026-10-27"})
    durations = [float(e["duration_ms"]) for e in fast.events()]
    await fast.tools.aclose()

    starts: list[float] = []
    lines: list[int] = []
    for _ in range(slow_runs):

        async def slow(request: httpx.Request) -> httpx.Response:
            await asyncio.sleep(slow_ms / 1000)
            return httpx.Response(200, json={"ok": True})

        h = make([http_spec(timeout_ms=5000)], handler=slow)
        said_at: list[float] = []
        original = h.backend.speak

        async def speak(text: str, allow_interruptions: bool, _orig=original, _at=said_at) -> None:
            _at.append(time.perf_counter())
            await _orig(text, allow_interruptions)

        h.backend.speak = speak  # type: ignore[method-assign]
        started = time.perf_counter()
        await h.tools.dispatch("check_availability", {"date": "2026-10-27"})
        lines.append(len(h.backend.said))
        if said_at:
            starts.append((said_at[0] - started) * 1000)
        await h.tools.aclose()
    return {
        "fast_duration_p50_ms": percentile(durations, 50),
        "fast_duration_p95_ms": percentile(durations, 95),
        "waiting_line_start_max_ms": max(starts) if starts else -1.0,
        "waiting_lines_per_call_max": float(max(lines)),
        "waiting_lines_per_call_min": float(min(lines)),
    }


def gate(report: dict[str, float]) -> list[str]:
    problems = []
    if report["fast_duration_p95_ms"] > GATE_OVERHEAD_P95_MS:
        problems.append(
            f"0 ms stub p95 {report['fast_duration_p95_ms']} ms > {GATE_OVERHEAD_P95_MS}"
        )
    if not 0 <= report["waiting_line_start_max_ms"] <= GATE_WAITING_LINE_MS:
        problems.append(f"waiting line started at {report['waiting_line_start_max_ms']} ms")
    if report["waiting_lines_per_call_max"] != 1 or report["waiting_lines_per_call_min"] != 1:
        problems.append("the waiting line must be spoken exactly once")
    return problems


if __name__ == "__main__":
    result = asyncio.run(run())
    print(json.dumps(result, indent=2))
    sys.exit(1 if gate(result) else 0)
