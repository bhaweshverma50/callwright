"""Money test (003 T046, SC-004): 50 simultaneous admissions for the last slot admit exactly one."""

from __future__ import annotations

import asyncio

from app.calls import service as calls
from tests.runtime_support import Runtime, owner_sql

REQUESTS = 50


async def test_fifty_requests_for_the_last_slot(runtime: Runtime) -> None:
    _, ws = await runtime.workspace(concurrency=3)
    agent = runtime.versions.add_agent(ws)
    request = calls.AdmissionRequest(ws, agent.agent_id, "web", "inbound", version="draft", origin="test")
    # Two slots already taken: one remains.
    for _ in range(2):
        assert (await calls.admit(runtime.db, request, catalog=runtime.catalog)).admitted

    results = await asyncio.gather(
        *(calls.admit(runtime.db, request, catalog=runtime.catalog) for _ in range(REQUESTS))
    )
    admitted = [r for r in results if r.admitted]
    refused = [r for r in results if not r.admitted]
    assert len(admitted) == 1
    assert len(refused) == REQUESTS - 1
    assert {r.refusal.code for r in refused if r.refusal} == {"concurrency_limit"}
    rows = owner_sql(
        "select status, count(*) from calls where workspace_id = %s group by status order by status", (ws,)
    )
    assert rows == [("failed", REQUESTS - 1), ("queued", 3)]
