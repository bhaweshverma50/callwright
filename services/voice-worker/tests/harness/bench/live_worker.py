"""Job entry for the live benchmark: the production ``job_entry`` with fake vendors.

Runs in the agent server's job process. The fake vendor parameters (scripted transcripts,
delay profile, seed) travel in the dispatch metadata under ``bench``, next to ``call_id``,
exactly where the API puts ``call_id`` for a web call.
"""

from __future__ import annotations

from typing import Any

from tests.harness.bench.live_fakes import LiveFakeParams, live_registry
from worker.entry import job_entry, parse_dispatch_metadata


async def bench_job_entry(ctx: Any) -> None:
    metadata = parse_dispatch_metadata(getattr(ctx.job, "metadata", None))
    params = LiveFakeParams.from_json(metadata.get("bench") or {})
    await job_entry(ctx, live_registry(params))
