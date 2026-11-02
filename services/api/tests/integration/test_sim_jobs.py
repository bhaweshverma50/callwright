"""Simulation crons (008 T087, R13): the sweeper fails runs whose runner went silent and frees
their slots; retention clears persona briefs and simulated transcripts with the base call."""

from __future__ import annotations

import httpx

from app.simulator import dispatch
from app.simulator.jobs import purge_simulation_data, sweep_simulations
from tests.conftest import Account
from tests.runtime_support import SERVICE_HEADERS, idem, owner_sql
from tests.sim_support import SimEnv, make_agent, seed_live_call


async def test_sweeper_fails_silent_runs(
    sim_env: SimEnv, client: httpx.AsyncClient, account: Account
) -> None:
    h = account.headers
    agent = await make_agent(client, account)
    base = seed_live_call(account.workspace_id, agent)
    run = (
        await client.post(
            "/v1/simulation-runs",
            json={"agent_id": agent.agent_id, "mode": "replay", "base_call_id": base},
            headers={**h, **idem()},
        )
    ).json()
    srun = run["simulation_run_id"]
    await sim_env.run_api_jobs()
    assert srun in await dispatch.holders(sim_env.app.state.redis, account.workspace_id)
    assert (
        await client.get(f"/v1/internal/simulation-runs/{srun}/spec", headers=SERVICE_HEADERS)
    ).status_code == 200
    assert await sweep_simulations(sim_env.ctx()) == 0
    owner_sql("update simulation_runs set started_at = now() - interval '1 hour' where id = %s", (srun,))
    assert await sweep_simulations(sim_env.ctx()) == 1
    done = (await client.get(f"/v1/simulation-runs/{srun}", headers=h)).json()
    assert done["status"] == "failed" and done["error_message"] == "The simulation runner stopped answering."
    assert srun not in await dispatch.holders(sim_env.app.state.redis, account.workspace_id)
    call = owner_sql("select status from calls where id = %s", (done["output_call_id"],))
    assert call[0][0] == "failed"


async def test_sweeper_finishes_unanswered_test_cases(
    sim_env: SimEnv, client: httpx.AsyncClient, account: Account
) -> None:
    h = account.headers
    agent = await make_agent(client, account)
    await client.post(
        "/v1/test-cases/import",
        json={"agent_id": agent.agent_id, "test_cases": [{"user_prompt": "a", "expected_behaviour": "b"}]},
        headers=h,
    )
    run = (
        await client.post("/v1/test-runs", json={"agent_id": agent.agent_id}, headers={**h, **idem()})
    ).json()
    await sim_env.run_api_jobs()
    assert await sweep_simulations(sim_env.ctx()) == 0
    owner_sql(
        "update test_runs set created_at = now() - interval '2 hours' where id = %s", (run["test_run_id"],)
    )
    assert await sweep_simulations(sim_env.ctx()) == 1
    done = (await client.get(f"/v1/test-runs/{run['test_run_id']}", headers=h)).json()
    assert done["status"] == "completed" and done["errored"] == 1
    assert done["results"][0]["error_message"] == "The test runner stopped answering."


async def test_retention_follows_the_base_call(
    sim_env: SimEnv, client: httpx.AsyncClient, account: Account
) -> None:
    h = account.headers
    agent = await make_agent(client, account)
    base = seed_live_call(account.workspace_id, agent)
    run = (
        await client.post(
            "/v1/simulation-runs",
            json={"agent_id": agent.agent_id, "mode": "persona", "base_call_id": base},
            headers={**h, **idem()},
        )
    ).json()
    await sim_env.drain()
    done = (await client.get(f"/v1/simulation-runs/{run['simulation_run_id']}", headers=h)).json()
    assert done["persona_brief"] is not None
    assert await purge_simulation_data(sim_env.ctx()) == 0
    owner_sql("update calls set transcript = null where id = %s", (base,))
    assert await purge_simulation_data(sim_env.ctx()) == 2
    after = (await client.get(f"/v1/simulation-runs/{run['simulation_run_id']}", headers=h)).json()
    assert after["persona_brief"] is None
    assert owner_sql("select transcript from calls where id = %s", (done["output_call_id"],))[0][0] is None


async def test_semaphore_is_idempotent_and_expires(sim_env: SimEnv) -> None:
    redis = sim_env.app.state.redis
    ws = "ws_semaphore_test"
    await redis.delete(dispatch.semaphore_key(ws))
    assert await dispatch.acquire(redis, ws, "a", 2, now=1000.0)
    assert await dispatch.acquire(redis, ws, "a", 2, now=1001.0)
    assert await dispatch.acquire(redis, ws, "b", 2, now=1002.0)
    assert not await dispatch.acquire(redis, ws, "c", 2, now=1003.0)
    assert await dispatch.acquire(redis, ws, "c", 2, now=1000.0 + dispatch.SLOT_TTL_S + 1)
    await dispatch.release(redis, ws, "c")
    assert await dispatch.holders(redis, ws) == ["b"]
