"""US3 end to end (008 T062): mixed agents refused, a 10-call batch with 2 failed runs, the
scorecard against hand-computed values, cancel mid-batch charging only finished runs, idempotent
start, batch-vs-batch baseline, completion hooks fired once, and the concurrency cap."""

from __future__ import annotations

import httpx

from app.evaluators.registry import builtin_id
from app.simulator import service as sim_service
from tests.conftest import Account
from tests.quality_support import seed_run
from tests.runtime_support import idem, owner_sql
from tests.sim_support import SimEnv, make_agent, seed_live_call

INTENT = builtin_id("intent_fulfillment")


def outputs(experiment_id: str) -> dict[str, str]:
    rows = owner_sql(
        "select base_call_id, output_call_id from simulation_runs "
        "where experiment_id = %s and status = 'completed'",
        (experiment_id,),
    )
    return {b: o for b, o in rows}


async def test_batch_scorecard_and_failures(
    sim_env: SimEnv, client: httpx.AsyncClient, account: Account
) -> None:
    h = account.headers
    ws = account.workspace_id
    agent = await make_agent(client, account)
    other = await make_agent(client, account)
    calls = [seed_live_call(ws, agent) for _ in range(10)]

    mixed = await client.post(
        "/v1/experiments",
        json={
            "agent_id": agent.agent_id,
            "mode": "replay",
            "base_call_ids": [*calls[:2], seed_live_call(ws, other)],
        },
        headers={**h, **idem()},
    )
    assert mixed.status_code == 422 and mixed.json()["code"] == "mixed_agents"
    single = await client.post(
        "/v1/experiments",
        json={"agent_id": agent.agent_id, "mode": "replay", "base_call_ids": calls[:1]},
        headers={**h, **idem()},
    )
    assert single.status_code == 422

    fired: list[str] = []

    async def hook(workspace_id: str, experiment_id: str) -> None:
        fired.append(experiment_id)

    sim_service.on_experiment_finished("call_selection", hook)
    try:
        key = idem()
        body = {"agent_id": agent.agent_id, "mode": "replay", "base_call_ids": calls, "name": "Prompt v2"}
        started = await client.post("/v1/experiments", json=body, headers={**h, **key})
        assert started.status_code == 202, started.text
        exp = started.json()
        assert exp["total_count"] == 10 and exp["status"] == "pending" and exp["source"] == "call_selection"
        again = await client.post("/v1/experiments", json=body, headers={**h, **key})
        assert again.json()["experiment_id"] == exp["experiment_id"]
        assert (
            owner_sql("select count(*) from simulation_experiments where agent_id = %s", (agent.agent_id,))[
                0
            ][0]
            == 1
        )

        failing = set(calls[8:])
        bases = dict(
            owner_sql(
                "select id, base_call_id from simulation_runs where experiment_id = %s",
                (exp["experiment_id"],),
            )
        )

        async def runner(name: str, args: tuple[object, ...]) -> None:
            run_id = str(args[0])
            if bases[run_id] in failing:
                await sim_env.runner.simulation(run_id, fail="The agent model was unavailable")
            else:
                await sim_env.runner.simulation(run_id)

        await sim_env.drain(runner)
        assert fired == [exp["experiment_id"]]
    finally:
        sim_service.clear_hooks("call_selection")

    batch = (await client.get(f"/v1/experiments/{exp['experiment_id']}", headers=h)).json()
    assert batch["status"] == "completed" and batch["completed_count"] == 8 and batch["failed_count"] == 2
    assert batch["cost_usd"] > 0 and batch["name"] == "Prompt v2"

    # Hand-made verdicts on top of the pipeline's: intent passes on 4 originals and on 6 of the 8
    # simulations, with flips computed from these rows.
    sims = outputs(exp["experiment_id"])
    owner_sql(
        "update evaluator_runs set superseded_at = now() where evaluator_id = %s and call_id = any(%s)",
        (INTENT, [*calls, *sims.values()]),
    )
    base_pass = set(calls[:4])
    sim_pass = set(calls[2:8])
    for c in calls:
        seed_run(ws, c, agent.agent_id, "intent_fulfillment", "pass" if c in base_pass else "fail")
    for b, o in sims.items():
        seed_run(ws, o, agent.agent_id, "intent_fulfillment", "pass" if b in sim_pass else "fail")
    card = (await client.get(f"/v1/experiments/{exp['experiment_id']}/scorecard", headers=h)).json()
    row = next(r for r in card["evaluators"] if r["evaluator_id"] == INTENT)
    assert (row["base_n"], row["base_passes"], row["sim_n"], row["sim_passes"]) == (10, 4, 8, 6)
    assert row["base_pass_rate"] == 0.4 and row["sim_pass_rate"] == 0.75 and row["delta_pp"] == 35.0
    # Pairs over the 8 simulated calls: c0,c1 pass->fail; c2,c3 pass->pass; c4..c7 fail->pass.
    assert row["pairs"] == {
        "n": 8,
        "improved": 4,
        "regressed": 2,
        "unchanged_pass": 2,
        "unchanged_fail": 0,
        "version_mismatch": 0,
    }
    assert card["base_call_count"] == 10 and card["sim_call_count"] == 8
    assert {e["status"] for e in card["excluded_runs"]} == {"failed"} and len(card["excluded_runs"]) == 2
    assert all(e["error_message"] == "The agent model was unavailable" for e in card["excluded_runs"])

    runs = (await client.get(f"/v1/experiments/{exp['experiment_id']}/runs?page_size=100", headers=h)).json()
    assert runs["total"] == 10

    # A second batch over the same calls, compared with the first as the baseline.
    second = (
        await client.post(
            "/v1/experiments",
            json={"agent_id": agent.agent_id, "mode": "replay", "base_call_ids": calls[:4]},
            headers={**h, **idem()},
        )
    ).json()
    await sim_env.drain()
    second_sims = outputs(second["experiment_id"])
    owner_sql(
        "update evaluator_runs set superseded_at = now() where evaluator_id = %s and call_id = any(%s)",
        (INTENT, list(second_sims.values())),
    )
    for o in second_sims.values():
        seed_run(ws, o, agent.agent_id, "intent_fulfillment", "pass")
    vs = (
        await client.get(
            f"/v1/experiments/{second['experiment_id']}/scorecard?baseline=experiment"
            f"&baseline_experiment_id={exp['experiment_id']}",
            headers=h,
        )
    ).json()
    vs_row = next(r for r in vs["evaluators"] if r["evaluator_id"] == INTENT)
    assert vs["baseline"] == "experiment" and vs["baseline_experiment_id"] == exp["experiment_id"]
    # Batch A on c0..c3: fail, fail, pass, pass -> 2/4; batch B: 4/4.
    assert (vs_row["base_n"], vs_row["base_passes"], vs_row["sim_passes"]) == (4, 2, 4)
    assert vs_row["delta_pp"] == 50.0 and vs_row["pairs"]["improved"] == 2
    bad = await client.get(
        f"/v1/experiments/{second['experiment_id']}/scorecard?baseline=experiment", headers=h
    )
    assert bad.status_code == 422

    listed = (await client.get(f"/v1/experiments?agent_id={agent.agent_id}", headers=h)).json()
    assert listed["total"] == 2 and listed["items"][0]["agent_name"] == agent.body["name"]
    assert (await client.get(f"/v1/experiments?agent_id={other.agent_id}", headers=h)).json()["total"] == 0


async def test_cancel_charges_only_finished_runs(
    sim_env: SimEnv, client: httpx.AsyncClient, account: Account
) -> None:
    h = account.headers
    agent = await make_agent(client, account)
    calls = [seed_live_call(account.workspace_id, agent) for _ in range(4)]
    exp = (
        await client.post(
            "/v1/experiments",
            json={"agent_id": agent.agent_id, "mode": "replay", "base_call_ids": calls},
            headers={**h, **idem()},
        )
    ).json()
    await sim_env.run_api_jobs()
    first, *rest = sim_env.textsim.jobs
    sim_env.textsim.jobs = rest
    await sim_env.runner.simulation(str(first[1][0]))
    # One more run is in progress when the operator cancels.
    in_flight = str(rest[0][1][0])
    spec = await client.get(
        f"/v1/internal/simulation-runs/{in_flight}/spec",
        headers={"Authorization": "Bearer dev-service-token"},
    )
    assert spec.status_code == 200
    owner_sql(
        "update simulation_runs set dispatched_at = null "
        "where id <> %s and experiment_id = %s and status = 'pending'",
        (in_flight, exp["experiment_id"]),
    )
    cancelled = (await client.post(f"/v1/experiments/{exp['experiment_id']}/cancel", headers=h)).json()
    assert cancelled["cancelled_count"] == 2 and cancelled["status"] == "running"
    sim_env.textsim.jobs = []
    # The in-flight run finishes (its spec was already fetched); the others never start.
    events = await client.post(
        f"/v1/internal/simulation-runs/{in_flight}/result",
        json={
            "status": "completed",
            "usage": {"agent": {"model": "azure_openai/gpt-5.1", "input_tokens": 100, "output_tokens": 10}},
        },
        headers={"Authorization": "Bearer dev-service-token"},
    )
    assert events.status_code == 204
    final = (await client.get(f"/v1/experiments/{exp['experiment_id']}", headers=h)).json()
    assert final["status"] == "cancelled" and final["completed_count"] == 2 and final["cancelled_count"] == 2
    charged = owner_sql(
        "select count(*) from usage_events where feature_key = 'simulation.replay' and ref_id in "
        "(select id from simulation_runs where experiment_id = %s)",
        (exp["experiment_id"],),
    )
    assert charged[0][0] == 2


async def test_concurrency_cap_queues_the_rest(
    sim_env: SimEnv, client: httpx.AsyncClient, account: Account
) -> None:
    from app.testing import dispatch

    h = account.headers
    agent = await make_agent(client, account)
    calls = [seed_live_call(account.workspace_id, agent) for _ in range(12)]
    await client.post(
        "/v1/experiments",
        json={"agent_id": agent.agent_id, "mode": "replay", "base_call_ids": calls},
        headers={**h, **idem()},
    )
    await sim_env.run_api_jobs(include_deferred=False)
    assert len(sim_env.textsim.jobs) == 10
    assert len(await dispatch.holders(sim_env.app.state.redis, account.workspace_id)) == 10
    waiting = [j for j in sim_env.queue.jobs if j.name == "dispatch_simulation"]
    assert len(waiting) == 2 and all(j.defer_by_s == dispatch.RETRY_DEFER_S for j in waiting)
    await sim_env.drain()
    assert await dispatch.holders(sim_env.app.state.redis, account.workspace_id) == []
    done = owner_sql(
        "select count(*) from simulation_runs where agent_id = %s and status = 'completed'", (agent.agent_id,)
    )
    assert done[0][0] == 12


async def test_no_credit(sim_env: SimEnv, client: httpx.AsyncClient, account: Account) -> None:
    from decimal import Decimal

    from app.billing import service as billing

    h = account.headers
    agent = await make_agent(client, account)
    calls = [seed_live_call(account.workspace_id, agent) for _ in range(3)]
    exp = (
        await client.post(
            "/v1/experiments",
            json={"agent_id": agent.agent_id, "mode": "replay", "base_call_ids": calls},
            headers={**h, **idem()},
        )
    ).json()
    async with sim_env.app.state.db.transaction(workspace_id=account.workspace_id) as session:
        balance = await billing.get_balance(session, account.workspace_id)
        await billing.post_transaction(
            session,
            workspace_id=account.workspace_id,
            type="adjustment",
            amount_usd=-balance,
            description="test",
        )
        assert await billing.get_balance(session, account.workspace_id) == Decimal(0)
    await sim_env.drain()
    final = (await client.get(f"/v1/experiments/{exp['experiment_id']}", headers=h)).json()
    assert final["status"] == "failed" and final["failed_count"] == 3
    runs = (await client.get(f"/v1/experiments/{exp['experiment_id']}/runs", headers=h)).json()["items"]
    assert {r["error_message"] for r in runs} == {"insufficient credit"}
    refused = await client.post(
        "/v1/experiments",
        json={"agent_id": agent.agent_id, "mode": "replay", "base_call_ids": calls},
        headers={**h, **idem()},
    )
    assert refused.status_code == 402
