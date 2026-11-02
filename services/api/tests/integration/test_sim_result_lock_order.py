"""Lock order between a simulation result and its call's post-call pipeline (deadlock fix).

The pipeline's analyze step holds the simulated call FOR UPDATE and then takes the workspace
billing lock. Recording the run's result must therefore wait on the call row before it charges,
never hold the billing lock while it waits for the call."""

from __future__ import annotations

import asyncio

import httpx
from sqlalchemy import select, text

from app.calls.models import Call
from app.simulator import service
from tests.conftest import Account
from tests.runtime_support import idem
from tests.sim_support import SimEnv, make_agent, seed_live_call

SERVICE = {"Authorization": "Bearer dev-service-token"}
RESULT = {
    "status": "completed",
    "end_reason": "caller_turns_exhausted",
    "usage": {"agent": {"model": "x/gpt-5.1", "input_tokens": 50, "output_tokens": 20}},
}


async def test_result_waits_for_the_call_row_before_taking_the_billing_lock(
    sim_env: SimEnv, client: httpx.AsyncClient, account: Account
) -> None:
    ws = account.workspace_id
    agent = await make_agent(client, account)
    base = seed_live_call(ws, agent)
    started = await client.post(
        "/v1/simulation-runs",
        json={"agent_id": agent.agent_id, "mode": "replay", "base_call_id": base},
        headers={**account.headers, **idem()},
    )
    run_id = started.json()["simulation_run_id"]
    spec = await client.get(f"/v1/internal/simulation-runs/{run_id}/spec", headers=SERVICE)
    assert spec.status_code == 200, spec.text
    output_call = spec.json()["output_call_id"]
    db = sim_env.app.state.db

    pipeline_has_row = asyncio.Event()
    release_pipeline = asyncio.Event()

    async def pipeline_step() -> bool:
        # Stands in for the analyze step: call row first, then (later) the billing lock.
        async with db.transaction(workspace_id=ws) as session:
            await session.execute(select(Call).where(Call.id == output_call).with_for_update())
            pipeline_has_row.set()
            await release_pipeline.wait()
            got = (
                await session.execute(
                    text("select pg_try_advisory_xact_lock(hashtextextended(:ws, 0))"), {"ws": ws}
                )
            ).scalar_one()
            return bool(got)

    async def record() -> None:
        async with db.transaction(workspace_id=ws) as session:
            assert await service.record_result(session, run_id, RESULT) is not None

    pipeline = asyncio.create_task(pipeline_step())
    await pipeline_has_row.wait()
    result = asyncio.create_task(record())
    await asyncio.sleep(0.5)  # the result is now waiting on the call row, holding no billing lock
    assert not result.done()
    release_pipeline.set()
    assert await asyncio.wait_for(pipeline, 10), "the result held the billing lock while waiting"
    await asyncio.wait_for(result, 10)
    run = (await client.get(f"/v1/simulation-runs/{run_id}", headers=account.headers)).json()
    assert run["status"] == "completed" and run["cost_usd"] > 0
