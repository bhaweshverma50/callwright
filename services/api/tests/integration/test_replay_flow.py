"""US2 end to end (008 T046): pre-flight, replay start, idempotent retry, completion, evaluation
of both sides at the same evaluator version, one feature charge and no call charge."""

from __future__ import annotations

import copy

import httpx
from sqlalchemy import select

from app.billing.models import CreditTransaction
from app.evaluators.registry import builtin_id
from app.usage.models import UsageEvent
from tests.conftest import Account
from tests.runtime_support import idem, owner_sql
from tests.sim_support import SimEnv, make_agent, seed_live_call

INTENT = builtin_id("intent_fulfillment")
HTTP_TOOL_NO_MOCK = "check_availability"


async def enable(
    client: httpx.AsyncClient, account: Account, agent_id: str, evaluator_id: str = INTENT
) -> None:
    response = await client.put(
        f"/v1/agents/{agent_id}/eval-settings/{evaluator_id}", json={"enabled": True}, headers=account.headers
    )
    assert response.status_code == 200, response.text


async def feature_events(env: SimEnv, ws: str) -> list[UsageEvent]:
    async with env.app.state.db.transaction(workspace_id=ws) as session:
        rows = await session.execute(select(UsageEvent).where(UsageEvent.workspace_id == ws))
        return list(rows.scalars())


async def test_replay_end_to_end(sim_env: SimEnv, client: httpx.AsyncClient, account: Account) -> None:
    h = account.headers
    ws = account.workspace_id
    agent = await make_agent(client, account)
    await enable(client, account, agent.agent_id)
    base = seed_live_call(
        ws, agent, tools=[{"after": 3, "name": HTTP_TOOL_NO_MOCK, "output": '{"slots": ["10:00"]}'}]
    )

    pre = await client.post(
        "/v1/simulations/preflight",
        json={
            "agent_id": agent.agent_id,
            "mode": "replay",
            "target": {"type": "published"},
            "base_call_ids": [base],
        },
        headers=h,
    )
    assert pre.status_code == 200, pre.text
    assert pre.json()["run_count"] == 1 and pre.json()["invalid_calls"] == []
    assert pre.json()["estimated_cost_usd"] > 0

    key = idem()
    body = {"agent_id": agent.agent_id, "mode": "replay", "base_call_id": base}
    started = await client.post("/v1/simulation-runs", json=body, headers={**h, **key})
    assert started.status_code == 202, started.text
    run = started.json()
    assert run["status"] == "pending" and run["target_type"] == "published"
    assert run["agent_name"] == agent.body["name"]
    retried = await client.post("/v1/simulation-runs", json=body, headers={**h, **key})
    assert retried.json()["simulation_run_id"] == run["simulation_run_id"]
    assert owner_sql("select count(*) from simulation_runs where agent_id = %s", (agent.agent_id,))[0][0] == 1

    tool = {"name": HTTP_TOOL_NO_MOCK, "output": '{"slots": ["10:00"]}', "answer_source": "recorded"}

    async def runner(name: str, args: tuple[object, ...]) -> None:
        result = await sim_env.runner.simulation(str(args[0]), tool=tool)
        assert result is not None
        spec = result.spec
        assert spec["mode"] == "replay" and spec["start_speaker"] == "agent"
        assert spec["caller_turns"] == [
            "I'd like to book a cleaning, Tuesday if possible.",
            "Yes please.",
            "No, thanks a lot.",
        ]
        assert spec["recorded_tool_outputs"] == [
            {"name": HTTP_TOOL_NO_MOCK, "output": '{"slots": ["10:00"]}'}
        ]
        assert spec["dynamic_variables"]["customer_name"] == "Priya"
        assert spec["runtime"]["config"]["prompt"]

    await sim_env.drain(runner)
    done = (await client.get(f"/v1/simulation-runs/{run['simulation_run_id']}", headers=h)).json()
    assert done["status"] == "completed", done
    assert done["end_reason"] == "caller_turns_exhausted"
    assert done["answer_source_counts"]["recorded"] == 1
    assert done["cost_usd"] > 0 and done["eval_status"] == "completed"
    output = done["output_call_id"]
    origin = owner_sql(
        "select origin, status, simulation_run_id, cost_total_usd from calls where id = %s", (output,)
    )
    assert origin[0][:3] == ("simulation", "completed", run["simulation_run_id"]) and origin[0][3] is None

    # Exactly one simulation.replay charge, no call charge for the simulated call.
    events = await feature_events(sim_env, ws)
    assert [e.feature_key for e in events].count("simulation.replay") == 1
    async with sim_env.app.state.db.transaction(workspace_id=ws) as session:
        call_charges = (
            await session.execute(
                select(CreditTransaction).where(
                    CreditTransaction.workspace_id == ws, CreditTransaction.type == "call_charge"
                )
            )
        ).scalars()
        assert list(call_charges) == []
    # A retried result does not charge again.
    again = await client.post(
        f"/v1/internal/simulation-runs/{run['simulation_run_id']}/result",
        json={
            "status": "completed",
            "usage": {"agent": {"model": "x/gpt-5.1", "input_tokens": 5, "output_tokens": 5}},
        },
        headers={"Authorization": "Bearer dev-service-token"},
    )
    assert again.status_code == 204
    assert [e.feature_key for e in await feature_events(sim_env, ws)].count("simulation.replay") == 1

    # Comparison: both transcripts, the tool badge, a verdict row on both sides at one version.
    cmp = (await client.get(f"/v1/simulation-runs/{run['simulation_run_id']}/comparison", headers=h)).json()
    assert cmp["original"]["call_id"] == base and cmp["simulated"]["call_id"] == output
    assert any(i.get("answer_source") == "recorded" for i in cmp["simulated"]["transcript"])
    assert cmp["original"]["transcript"][0] == {
        "type": "message",
        "role": "assistant",
        "content": "Hi, thanks for calling Bright Smiles. How can I help?",
        "node_id": None,
    }
    intent = next(v for v in cmp["verdicts"] if v["evaluator_id"] == INTENT)
    assert intent["original"] in ("pass", "fail") and intent["simulated"] in ("pass", "fail")
    assert intent["change"] in ("improved", "regressed", "unchanged")
    versions = owner_sql(
        "select call_id, evaluator_version from evaluator_runs where evaluator_id = %s and call_id = any(%s)",
        (INTENT, [base, output]),
    )
    assert {c for c, _ in versions} == {base, output} and len({v for _, v in versions}) == 1

    # Hidden from Call History unless asked for.
    history = (await client.get(f"/v1/calls?agent_id={agent.agent_id}", headers=h)).json()
    assert output not in {c["call_id"] for c in history["items"]}
    with_sim = (
        await client.get(f"/v1/calls?agent_id={agent.agent_id}&origin=live,simulation", headers=h)
    ).json()
    assert output in {c["call_id"] for c in with_sim["items"]}


async def test_variant_target_and_runs_list(
    sim_env: SimEnv, client: httpx.AsyncClient, account: Account
) -> None:
    h = account.headers
    agent = await make_agent(client, account)
    base = seed_live_call(account.workspace_id, agent)
    version = (await client.get(f"/v1/agents/{agent.agent_id}/versions/{agent.version_id}", headers=h)).json()
    config = copy.deepcopy(version["config"])
    config["prompt"] = "You book cleanings. Confirm the date twice."
    run = (
        await client.post(
            "/v1/simulation-runs",
            json={
                "agent_id": agent.agent_id,
                "mode": "replay",
                "base_call_id": base,
                "target": {"type": "variant", "config": config, "label": "Confirm twice"},
            },
            headers={**h, **idem()},
        )
    ).json()
    assert run["target_type"] == "variant" and run["variant_label"] == "Confirm twice"
    await sim_env.drain()
    spec_prompt = owner_sql(
        "select config_snapshot->>'prompt' from simulation_runs where id = %s", (run["simulation_run_id"],)
    )
    assert spec_prompt[0][0] == config["prompt"]
    listed = (
        await client.get(f"/v1/simulation-runs?agent_id={agent.agent_id}&standalone=true", headers=h)
    ).json()
    assert listed["total"] == 1 and listed["items"][0]["status"] == "completed"
    by_call = (await client.get(f"/v1/simulation-runs?base_call_id={base}", headers=h)).json()
    assert by_call["total"] == 1


async def test_refusals(sim_env: SimEnv, client: httpx.AsyncClient, account: Account) -> None:
    h = account.headers
    agent = await make_agent(client, account)
    other = await make_agent(client, account)
    foreign = seed_live_call(account.workspace_id, other)
    unfinished = seed_live_call(account.workspace_id, agent, status="ended")
    purged = seed_live_call(account.workspace_id, agent, transcript=False)
    for call_id, reason in (
        (foreign, "mixed_agents"),
        (unfinished, "invalid_calls"),
        (purged, "invalid_calls"),
    ):
        response = await client.post(
            "/v1/simulation-runs",
            json={"agent_id": agent.agent_id, "mode": "replay", "base_call_id": call_id},
            headers={**h, **idem()},
        )
        assert response.status_code == 422 and response.json()["code"] == reason, response.text
    no_base = await client.post(
        "/v1/simulation-runs", json={"agent_id": agent.agent_id, "mode": "replay"}, headers={**h, **idem()}
    )
    assert no_base.status_code == 422
    pre = (
        await client.post(
            "/v1/simulations/preflight",
            json={
                "agent_id": agent.agent_id,
                "mode": "replay",
                "target": {"type": "published"},
                "base_call_ids": [unfinished, purged],
            },
            headers=h,
        )
    ).json()
    assert pre["invalid_calls"] == [
        {"call_id": unfinished, "reason": "not_completed"},
        {"call_id": purged, "reason": "unavailable"},
    ]
    pending = (
        await client.post(
            "/v1/simulation-runs",
            json={
                "agent_id": agent.agent_id,
                "mode": "replay",
                "base_call_id": seed_live_call(account.workspace_id, agent),
            },
            headers={**h, **idem()},
        )
    ).json()
    cancelled = await client.post(f"/v1/simulation-runs/{pending['simulation_run_id']}/cancel", headers=h)
    assert cancelled.status_code == 200 and cancelled.json()["status"] == "cancelled"
    await sim_env.drain()
    assert sim_env.runner.calls == []
    assert (
        await client.post(f"/v1/simulation-runs/{pending['simulation_run_id']}/cancel", headers=h)
    ).status_code == 409
    early = await client.get(f"/v1/simulation-runs/{pending['simulation_run_id']}/comparison", headers=h)
    assert early.status_code == 409
