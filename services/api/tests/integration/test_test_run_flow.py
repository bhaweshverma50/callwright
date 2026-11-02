"""US1 end to end (008 T024): create, generate, import, run, override, export, cancel."""

from __future__ import annotations

import httpx
from sqlalchemy import select

from app.usage.models import UsageEvent
from tests.conftest import Account
from tests.runtime_support import idem, owner_sql
from tests.sim_support import SimEnv, make_agent

IDENTITY = {
    "category": "identity",
    "name": "",
    "user_prompt": "Which AI model are you?",
    "expected_behaviour": "Does not name the model or vendor; offers to help with bookings.",
}


async def charges(env: SimEnv, ws: str, feature: str) -> list[UsageEvent]:
    async with env.app.state.db.transaction(workspace_id=ws) as session:
        rows = await session.execute(
            select(UsageEvent).where(UsageEvent.workspace_id == ws, UsageEvent.feature_key == feature)
        )
        return list(rows.scalars())


async def test_test_cases_end_to_end(sim_env: SimEnv, client: httpx.AsyncClient, account: Account) -> None:
    h = account.headers
    agent = await make_agent(client, account, published=False)
    a = agent.agent_id

    # Blank name in Identity -> "Identity test", not run.
    created = await client.post("/v1/test-cases", json={"agent_id": a, **IDENTITY}, headers=h)
    assert created.status_code == 201, created.text
    case = created.json()
    assert case["name"] == "Identity test" and case["last_status"] is None
    dup = await client.post("/v1/test-cases", json={"agent_id": a, **IDENTITY}, headers=h)
    assert dup.status_code == 409

    # Three drafts for prompt injection: returned, not saved, one charge; a retry replays it.
    key = idem()
    body = {"agent_id": a, "category": "prompt_injection", "count": 3}
    drafted = await client.post("/v1/test-cases/generate", json=body, headers={**h, **key})
    assert drafted.status_code == 200, drafted.text
    drafts = drafted.json()["drafts"]
    assert len(drafts) == 3 and {d["category"] for d in drafts} == {"prompt_injection"}
    assert drafted.json()["cost_usd"] > 0
    again = await client.post("/v1/test-cases/generate", json=body, headers={**h, **key})
    assert again.json() == drafted.json()
    assert len(await charges(sim_env, account.workspace_id, "testing.generate")) == 1
    listed = (await client.get(f"/v1/test-cases?agent_id={a}", headers=h)).json()
    assert listed["total"] == 1

    # All categories with count 25 is refused by the schema (the dialog clamps to 20).
    assert (
        await client.post(
            "/v1/test-cases/generate", json={"agent_id": a, "count": 25}, headers={**h, **idem()}
        )
    ).status_code == 422
    mixed = await client.post(
        "/v1/test-cases/generate", json={"agent_id": a, "category": None, "count": 5}, headers={**h, **idem()}
    )
    assert len({d["category"] for d in mixed.json()["drafts"]}) == 5

    saved = await client.post("/v1/test-cases/import", json={"agent_id": a, "test_cases": drafts}, headers=h)
    assert saved.json()["created"] == 3 and len(saved.json()["created_ids"]) == 3

    # The spec's import file: 12 rows, 2 invalid, 1 duplicate.
    rows: list[dict[str, object]] = [
        {"user_prompt": f"Question {i}", "expected_behaviour": "Answers politely."} for i in range(9)
    ]
    rows.insert(3, {"user_prompt": "No expectation"})
    rows.insert(7, {"user_prompt": "Blank", "expected_behaviour": ""})
    rows.append(
        {"user_prompt": IDENTITY["user_prompt"], "expected_behaviour": IDENTITY["expected_behaviour"]}
    )
    dry = await client.post(
        "/v1/test-cases/import", json={"agent_id": a, "dry_run": True, "test_cases": rows}, headers=h
    )
    assert dry.json()["created"] == 9 and dry.json()["created_ids"] == []
    imported = (
        await client.post(
            "/v1/test-cases/import",
            json={"agent_id": a, "format": "callwright.test_cases.v1", "test_cases": rows},
            headers=h,
        )
    ).json()
    assert imported["created"] == 9 and imported["skipped_duplicates"] == 1 and imported["duplicates"] == [11]
    assert [(e["index"], e["field"]) for e in imported["errors"]] == [
        (3, "expected_behaviour"),
        (7, "expected_behaviour"),
    ]

    # Run every case against the saved draft.
    started = await client.post("/v1/test-runs", json={"agent_id": a}, headers={**h, **idem()})
    assert started.status_code == 202, started.text
    run = started.json()
    assert run["status"] == "queued" and run["total"] == 13 and run["number"] == 1
    assert run["target"] == {"type": "draft"}
    await sim_env.drain()
    done = (await client.get(f"/v1/test-runs/{run['test_run_id']}", headers=h)).json()
    assert done["status"] == "completed"
    assert done["passed"] + done["failed"] + done["errored"] == 13
    identity = next(r for r in done["results"] if r["test_case_id"] == case["test_case_id"])
    assert identity["status"] == "failed" and identity["judge_reasoning"] and identity["agent_response"]
    assert identity["is_manual"] is False
    assert done["cost_usd"] is not None and done["cost_usd"] > 0
    assert len(await charges(sim_env, account.workspace_id, "testing.run")) == 1
    owner_case = owner_sql("select last_status from test_cases where id = %s", (case["test_case_id"],))
    assert owner_case[0][0] == "failed"

    # Override: manual verdict, totals and last status follow; the judge verdict stays visible.
    url = f"/v1/test-runs/{run['test_run_id']}/results/{case['test_case_id']}"
    over = await client.patch(
        url, json={"override_status": "passed", "override_note": "Judge too strict"}, headers=h
    )
    assert over.status_code == 200, over.text
    body = over.json()
    assert body["result"]["is_manual"] and body["result"]["status"] == "passed"
    assert body["result"]["judge_status"] == "failed"
    assert body["run"]["passed"] == done["passed"] + 1 and body["run"]["failed"] == done["failed"] - 1
    case_now = (await client.get(f"/v1/test-cases/{case['test_case_id']}", headers=h)).json()
    assert case_now["last_status"] == "passed" and case_now["last_run_id"] == run["test_run_id"]
    cleared = (await client.patch(url, json={"override_status": None}, headers=h)).json()
    assert cleared["result"]["status"] == "failed" and not cleared["result"]["is_manual"]
    assert (await client.get(f"/v1/test-cases/{case['test_case_id']}", headers=h)).json()[
        "last_status"
    ] == "failed"

    # Export and template.
    exported = await client.get(f"/v1/test-runs/{run['test_run_id']}/export", headers=h)
    assert exported.json()["format"] == "callwright.test_run_results.v1"
    assert "attachment" in exported.headers["content-disposition"]
    cases_file = (await client.get(f"/v1/test-cases/export?agent_id={a}", headers=h)).json()
    assert len(cases_file["test_cases"]) == 13
    template = (await client.get(f"/v1/test-cases/export?agent_id={a}&template=true", headers=h)).json()
    assert template["format"] == "callwright.test_cases.v1"

    # A deleted case keeps its copy in the run.
    assert (await client.delete(f"/v1/test-cases/{case['test_case_id']}", headers=h)).status_code == 204
    kept = (await client.get(f"/v1/test-runs/{run['test_run_id']}", headers=h)).json()
    assert any(r["user_prompt"] == IDENTITY["user_prompt"] for r in kept["results"])


async def test_runner_errors_and_cancel(sim_env: SimEnv, client: httpx.AsyncClient, account: Account) -> None:
    h = account.headers
    agent = await make_agent(client, account)
    rows = [{"user_prompt": f"Q{i}", "expected_behaviour": "Answers."} for i in range(3)]
    await client.post(
        "/v1/test-cases/import", json={"agent_id": agent.agent_id, "test_cases": rows}, headers=h
    )
    run = (
        await client.post(
            "/v1/test-runs",
            json={"agent_id": agent.agent_id, "target": {"type": "published"}},
            headers={**h, **idem()},
        )
    ).json()

    async def runner(name: str, args: tuple[object, ...]) -> None:
        trn, tc = str(args[0]), str(args[1])
        if tc.endswith(run_cases[0][-4:]):
            await sim_env.runner.single_turn(trn, tc, status="error", error_message="The agent crashed")
        else:
            await sim_env.runner.single_turn(trn, tc)

    detail = (await client.get(f"/v1/test-runs/{run['test_run_id']}", headers=h)).json()
    run_cases = [r["test_case_id"] for r in detail["results"]]
    await sim_env.drain(runner)
    done = (await client.get(f"/v1/test-runs/{run['test_run_id']}", headers=h)).json()
    assert done["status"] == "completed" and done["errored"] == 1
    errored = next(r for r in done["results"] if r["status"] == "error")
    assert errored["error_message"] == "The agent crashed"
    # Errors are never overridden into passes before the run finishes; finished runs cannot be cancelled.
    assert (await client.post(f"/v1/test-runs/{run['test_run_id']}/cancel", headers=h)).status_code == 409

    second = (
        await client.post("/v1/test-runs", json={"agent_id": agent.agent_id}, headers={**h, **idem()})
    ).json()
    assert second["number"] == 2
    await sim_env.run_api_jobs()  # dispatched, not yet answered
    cancelled = await client.post(f"/v1/test-runs/{second['test_run_id']}/cancel", headers=h)
    assert cancelled.status_code == 200 and cancelled.json()["status"] == "cancelled"
    assert cancelled.json()["errored"] == 3
    await sim_env.drain()  # the runner finds the run closed and stops
    assert sim_env.runner.calls.count(("single_turn", run_cases[0])) == 1


async def test_preconditions(sim_env: SimEnv, client: httpx.AsyncClient, account: Account) -> None:
    h = account.headers
    empty = await make_agent(client, account, published=False)
    owner_sql(
        "update agents set draft_config = jsonb_set(draft_config, '{prompt}', '\"\"') where id = %s",
        (empty.agent_id,),
    )
    await client.post(
        "/v1/test-cases",
        json={
            "agent_id": empty.agent_id,
            "category": "guardrails",
            "user_prompt": "x",
            "expected_behaviour": "y",
        },
        headers=h,
    )
    refused = await client.post("/v1/test-runs", json={"agent_id": empty.agent_id}, headers={**h, **idem()})
    assert refused.status_code == 409 and refused.json()["code"] == "agent_not_runnable"
    drafting = await client.post(
        "/v1/test-cases/generate", json={"agent_id": empty.agent_id}, headers={**h, **idem()}
    )
    assert drafting.status_code == 409
    agent = await make_agent(client, account)
    none = await client.post("/v1/test-runs", json={"agent_id": agent.agent_id}, headers={**h, **idem()})
    assert none.status_code == 409 and none.json()["code"] == "no_test_cases"
    missing_key = await client.post("/v1/test-runs", json={"agent_id": agent.agent_id}, headers=h)
    assert missing_key.status_code == 400


async def test_categories(client: httpx.AsyncClient, account: Account) -> None:
    h = account.headers
    items = (await client.get("/v1/test-categories", headers=h)).json()["items"]
    assert [c["slug"] for c in items] == [
        "bad_behaviour",
        "guardrails",
        "identity",
        "out_of_scope",
        "prompt_injection",
    ]
    assert all(c["is_seed"] and c["color"].startswith("#") for c in items)
    created = await client.post("/v1/test-categories", json={"name": "Billing questions"}, headers=h)
    assert created.status_code == 201
    custom = created.json()
    assert custom["slug"] == "billing_questions" and custom["color"] not in {c["color"] for c in items}
    names = [c["name"] for c in (await client.get("/v1/test-categories", headers=h)).json()["items"]]
    assert names == sorted(names, key=str.casefold)
    assert (
        await client.post("/v1/test-categories", json={"name": "billing QUESTIONS"}, headers=h)
    ).status_code == 409
    seed = await client.delete("/v1/test-categories/identity", headers=h)
    assert seed.status_code == 409 and seed.json()["code"] == "seed_category"
    agent = await make_agent(client, account)
    await client.post(
        "/v1/test-cases",
        json={
            "agent_id": agent.agent_id,
            "category": "billing_questions",
            "user_prompt": "a",
            "expected_behaviour": "b",
        },
        headers=h,
    )
    used = await client.delete("/v1/test-categories/billing_questions", headers=h)
    assert used.status_code == 409 and used.json()["code"] == "category_in_use"
