"""Contract tests for contracts/simulator.yaml (008 T043, T061): runs, pre-flight, comparison,
batches, scorecard and the runner's internal endpoints."""

from __future__ import annotations

import httpx

from tests.conftest import Account
from tests.contract.conftest import check
from tests.runtime_support import SERVICE_HEADERS, idem
from tests.sim_support import SimEnv, make_agent, seed_live_call

SRUN = "srun_01ARZ3NDEKTSV4RRFFQ69G5FAV"
EXP = "exp_01ARZ3NDEKTSV4RRFFQ69G5FAV"


async def test_run_operations(sim_env: SimEnv, client: httpx.AsyncClient, account: Account) -> None:
    h = account.headers
    agent = await make_agent(client, account)
    base = seed_live_call(account.workspace_id, agent, tools=[{"after": 1, "name": "lookup", "output": "{}"}])
    pre = await client.post(
        "/v1/simulations/preflight",
        json={
            "agent_id": agent.agent_id,
            "mode": "replay",
            "target": {"type": "published"},
            "base_call_ids": [base, "call_x"],
        },
        headers=h,
    )
    assert check(pre).json()["invalid_calls"] == [{"call_id": "call_x", "reason": "not_found"}]
    unpublished = await make_agent(client, account, published=False)
    no_version = await client.post(
        "/v1/simulations/preflight",
        json={"agent_id": unpublished.agent_id, "mode": "persona", "target": {"type": "published"}},
        headers=h,
    )
    assert check(no_version).status_code == 409
    bad = await client.post(
        "/v1/simulations/preflight",
        json={"agent_id": agent.agent_id, "mode": "replay", "target": {"type": "variant"}},
        headers=h,
    )
    assert check(bad).status_code == 422

    run = check(
        await client.post(
            "/v1/simulation-runs",
            json={"agent_id": agent.agent_id, "mode": "replay", "base_call_id": base},
            headers={**h, **idem()},
        )
    ).json()
    srun = run["simulation_run_id"]
    assert check(await client.get(f"/v1/simulation-runs/{srun}/comparison", headers=h)).status_code == 409
    check(await client.get(f"/v1/simulation-runs?agent_id={agent.agent_id}&status=pending", headers=h))
    await sim_env.run_api_jobs()
    spec = check(
        await client.get(f"/v1/internal/simulation-runs/{srun}/spec", headers=SERVICE_HEADERS)
    ).json()
    assert spec["channel"] == "web" and spec["caller_turns"]
    assert check(await client.post(f"/v1/simulation-runs/{srun}/cancel", headers=h)).status_code == 409
    sim_env.textsim.jobs.clear()
    await sim_env.runner.simulation(
        srun, tool={"name": "lookup", "output": "{}", "answer_source": "synthesized"}
    )
    check(await client.get(f"/v1/simulation-runs/{srun}", headers=h))
    check(await client.get(f"/v1/simulation-runs/{srun}/comparison", headers=h))
    assert (
        check(
            await client.get(f"/v1/internal/simulation-runs/{srun}/spec", headers=SERVICE_HEADERS)
        ).status_code
        == 409
    )
    assert check(await client.get(f"/v1/simulation-runs/{SRUN}", headers=h)).status_code == 404
    assert check(await client.get(f"/v1/simulation-runs/{SRUN}/comparison", headers=h)).status_code == 404
    assert check(await client.post(f"/v1/simulation-runs/{SRUN}/cancel", headers=h)).status_code == 404
    assert (
        check(
            await client.get(f"/v1/internal/simulation-runs/{SRUN}/spec", headers=SERVICE_HEADERS)
        ).status_code
        == 404
    )
    lost = await client.post(
        f"/v1/internal/simulation-runs/{SRUN}/result",
        json={"status": "failed", "usage": {}},
        headers=SERVICE_HEADERS,
    )
    assert check(lost).status_code == 404
    unpublished_run = await client.post(
        "/v1/simulation-runs",
        json={"agent_id": unpublished.agent_id, "mode": "persona", "persona_brief": {"goal": "Book"}},
        headers={**h, **idem()},
    )
    assert check(unpublished_run).status_code == 409


async def test_batch_operations(sim_env: SimEnv, client: httpx.AsyncClient, account: Account) -> None:
    h = account.headers
    agent = await make_agent(client, account)
    calls = [seed_live_call(account.workspace_id, agent) for _ in range(3)]
    exp = check(
        await client.post(
            "/v1/experiments",
            json={"agent_id": agent.agent_id, "mode": "replay", "base_call_ids": calls},
            headers={**h, **idem()},
        )
    ).json()
    e = exp["experiment_id"]
    check(await client.get(f"/v1/experiments?agent_id={agent.agent_id}&source=call_selection", headers=h))
    check(await client.get(f"/v1/experiments/{e}", headers=h))
    check(await client.get(f"/v1/experiments/{e}/runs", headers=h))
    await sim_env.drain()
    card = check(await client.get(f"/v1/experiments/{e}/scorecard", headers=h)).json()
    assert card["base_call_count"] == 3
    assert (
        check(await client.get(f"/v1/experiments/{e}/scorecard?baseline=experiment", headers=h)).status_code
        == 422
    )
    check(await client.post(f"/v1/experiments/{e}/cancel", headers=h))
    assert check(await client.get(f"/v1/experiments/{EXP}", headers=h)).status_code == 404
    assert check(await client.get(f"/v1/experiments/{EXP}/runs", headers=h)).status_code == 404
    assert check(await client.get(f"/v1/experiments/{EXP}/scorecard", headers=h)).status_code == 404
    assert check(await client.post(f"/v1/experiments/{EXP}/cancel", headers=h)).status_code == 404
    mixed = await client.post(
        "/v1/experiments",
        json={"agent_id": agent.agent_id, "mode": "replay", "base_call_ids": [calls[0], "call_x"]},
        headers={**h, **idem()},
    )
    assert check(mixed).status_code == 422
    unpublished = await make_agent(client, account, published=False)
    other_calls = [seed_live_call(account.workspace_id, unpublished) for _ in range(2)]
    refused = await client.post(
        "/v1/experiments",
        json={"agent_id": unpublished.agent_id, "mode": "replay", "base_call_ids": other_calls},
        headers={**h, **idem()},
    )
    assert check(refused).status_code == 409
