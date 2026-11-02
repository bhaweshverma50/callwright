"""US4 end to end (008 T070): a persona run from a base call stores the extracted brief; a
standalone brief run has no original side; persona and extraction charges."""

from __future__ import annotations

import httpx

from tests.conftest import Account
from tests.runtime_support import idem, owner_sql
from tests.sim_support import SimEnv, make_agent, seed_live_call

BRIEF = {
    "goal": "Move Thursday's 3 pm cleaning to next week",
    "known_facts": ["Name: Priya Shah"],
    "temperament": "Short on time",
    "speaking_style": "Brief answers",
    "constraints": ["Gives her name only when asked"],
}


def features(run_id: str) -> list[str]:
    rows = owner_sql("select feature_key from usage_events where ref_id = %s order by feature_key", (run_id,))
    return [r[0] for r in rows]


async def test_persona_from_a_base_call(sim_env: SimEnv, client: httpx.AsyncClient, account: Account) -> None:
    h = account.headers
    agent = await make_agent(client, account)
    base = seed_live_call(
        account.workspace_id,
        agent,
        lines=[
            ("agent", "Hello, Bright Smiles."),
            ("user", "Hi, this is Priya Shah, I need to move my cleaning."),
        ],
    )
    run = (
        await client.post(
            "/v1/simulation-runs",
            json={
                "agent_id": agent.agent_id,
                "mode": "persona",
                "base_call_id": base,
                "settings": {"max_caller_turns": 8},
            },
            headers={**h, **idem()},
        )
    ).json()
    assert run["persona_brief"] is None

    seen: dict[str, object] = {}

    async def runner(name: str, args: tuple[object, ...]) -> None:
        result = await sim_env.runner.simulation(str(args[0]), end_reason="caller_hung_up")
        assert result is not None
        seen.update(result.spec)

    await sim_env.drain(runner)
    assert seen["mode"] == "persona" and "caller_turns" not in seen
    assert seen["settings"] == {
        "max_caller_turns": 8,
        "missing_mock_policy": "synthesize",
        "persona_model": "openai/gpt-5-mini",
    }
    brief = seen["persona_brief"]
    assert isinstance(brief, dict) and brief["goal"].startswith("Hi, this is Priya Shah")
    assert "Name: Priya Shah" in brief["known_facts"]
    done = (await client.get(f"/v1/simulation-runs/{run['simulation_run_id']}", headers=h)).json()
    assert done["status"] == "completed" and done["persona_source"] == "extracted"
    assert done["persona_brief"] == brief and done["end_reason"] == "caller_hung_up"
    assert features(run["simulation_run_id"]) == ["simulation.persona", "simulation.persona_extraction"]
    cmp = (await client.get(f"/v1/simulation-runs/{run['simulation_run_id']}/comparison", headers=h)).json()
    assert cmp["original"]["call_id"] == base and cmp["unused_caller_turns"] == []


async def test_standalone_brief_on_an_agent_without_calls(
    sim_env: SimEnv, client: httpx.AsyncClient, account: Account
) -> None:
    h = account.headers
    agent = await make_agent(client, account)
    pre = (
        await client.post(
            "/v1/simulations/preflight",
            json={"agent_id": agent.agent_id, "mode": "persona", "target": {"type": "draft"}},
            headers=h,
        )
    ).json()
    assert pre["run_count"] == 1 and pre["estimated_cost_usd"] > 0
    run = (
        await client.post(
            "/v1/simulation-runs",
            json={
                "agent_id": agent.agent_id,
                "mode": "persona",
                "persona_brief": BRIEF,
                "target": {"type": "draft"},
            },
            headers={**h, **idem()},
        )
    ).json()
    assert run["persona_source"] == "provided" and run["base_call_id"] is None

    async def runner(name: str, args: tuple[object, ...]) -> None:
        await sim_env.runner.simulation(str(args[0]), end_reason="turn_limit_reached")

    await sim_env.drain(runner)
    done = (await client.get(f"/v1/simulation-runs/{run['simulation_run_id']}", headers=h)).json()
    assert done["status"] == "completed" and done["end_reason"] == "turn_limit_reached"
    assert done["persona_brief"]["goal"] == BRIEF["goal"]
    cmp = (await client.get(f"/v1/simulation-runs/{run['simulation_run_id']}/comparison", headers=h)).json()
    assert cmp["original"] is None and cmp["simulated"]["transcript"]
    assert all(v["original"] is None and v["change"] == "not_comparable" for v in cmp["verdicts"])
    assert features(run["simulation_run_id"]) == ["simulation.persona"]
    missing = await client.post(
        "/v1/simulation-runs", json={"agent_id": agent.agent_id, "mode": "persona"}, headers={**h, **idem()}
    )
    assert missing.status_code == 422
