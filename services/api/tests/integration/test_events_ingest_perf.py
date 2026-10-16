"""Events ingest performance (003 T108): p95 under 50 ms for 50-event batches on the local stack."""

from __future__ import annotations

import statistics
import time

import httpx

from tests.runtime_support import SERVICE_HEADERS, Events, Runtime, admitted_call

BATCHES = 40
BATCH_SIZE = 50
P95_BUDGET_MS = 50.0


async def test_fifty_event_batches_p95(client: httpx.AsyncClient, runtime: Runtime) -> None:
    setup = await admitted_call(runtime)
    ev = Events()
    url = f"/v1/internal/calls/{setup.call_id}/events"
    warm = await client.post(url, json={"events": [ev.status("in_progress")]}, headers=SERVICE_HEADERS)
    assert warm.status_code == 200
    timings: list[float] = []
    for b in range(BATCHES):
        batch = []
        for i in range(BATCH_SIZE - 1):
            if i % 3 == 0:
                batch.append(ev.turn(b * BATCH_SIZE + i))
            else:
                batch.append(ev.message("user" if i % 2 else "agent", f"utterance {b}-{i}"))
        batch.append(ev.usage(audio_ms=1000 * b))
        started = time.perf_counter()
        response = await client.post(url, json={"events": batch}, headers=SERVICE_HEADERS)
        timings.append((time.perf_counter() - started) * 1000)
        assert response.status_code == 200 and response.json()["accepted"] == BATCH_SIZE
    p95 = statistics.quantiles(timings, n=20)[18]
    print(f"events ingest: p50 {statistics.median(timings):.1f} ms, p95 {p95:.1f} ms")
    assert p95 < P95_BUDGET_MS, f"p95 {p95:.1f} ms over {P95_BUDGET_MS} ms"
