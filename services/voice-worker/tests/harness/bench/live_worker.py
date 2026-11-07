"""Job entry for the live benchmark: the production ``job_entry`` with fake or real vendors.

Runs in the agent server's job process. The vendor parameters (fakes: scripted transcripts,
delay profile, seed; real: the bench tool and slow-turn settings) travel in the dispatch
metadata under ``bench``, next to ``call_id``, exactly where the API puts ``call_id`` for a
web call.
"""

from __future__ import annotations

from typing import Any

from tests.harness.bench.live_fakes import LiveFakeParams, live_registry
from worker.entry import job_entry, parse_dispatch_metadata


async def bench_job_entry(ctx: Any) -> None:
    metadata = parse_dispatch_metadata(getattr(ctx.job, "metadata", None))
    bench = metadata.get("bench") or {}
    if bench.get("vendors") == "real":
        from tests.harness.bench.live_real import RealBenchParams, availability_tool, real_registry

        params = RealBenchParams.from_json(bench)
        await job_entry(ctx, real_registry(params), [availability_tool(params.tool_delay_ms)])
        return
    await job_entry(ctx, live_registry(LiveFakeParams.from_json(bench)))
