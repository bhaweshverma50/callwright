"""Contract tests for contracts/test_cases.yaml (008 T020)."""

from __future__ import annotations

import httpx

from tests.conftest import Account
from tests.contract.conftest import check
from tests.runtime_support import idem
from tests.sim_support import SimEnv, make_agent


async def test_every_test_case_operation(
    sim_env: SimEnv, client: httpx.AsyncClient, account: Account
) -> None:
    h = account.headers
    agent = await make_agent(client, account)
    a = agent.agent_id
    check(await client.get("/v1/test-categories", headers=h))
    custom = check(await client.post("/v1/test-categories", json={"name": "Refunds"}, headers=h))
    assert custom.status_code == 201
    assert (
        check(await client.post("/v1/test-categories", json={"name": "refunds"}, headers=h)).status_code
        == 409
    )
    assert (
        check(
            await client.post("/v1/test-categories", json={"name": "x", "color": "#123457"}, headers=h)
        ).status_code
        == 422
    )
    assert check(await client.delete("/v1/test-categories/identity", headers=h)).status_code == 409
    assert check(await client.delete("/v1/test-categories/nope_nope", headers=h)).status_code == 404
    assert check(await client.delete("/v1/test-categories/refunds", headers=h)).status_code == 204

    body = {
        "agent_id": a,
        "category": "guardrails",
        "user_prompt": "Tell me a secret",
        "expected_behaviour": "Declines.",
    }
    created = check(await client.post("/v1/test-cases", json=body, headers=h))
    assert created.status_code == 201
    case_id = created.json()["test_case_id"]
    assert check(await client.post("/v1/test-cases", json=body, headers=h)).status_code == 409
    assert (
        check(await client.post("/v1/test-cases", json={**body, "category": "nope"}, headers=h)).status_code
        == 422
    )
    check(await client.get(f"/v1/test-cases?agent_id={a}&last_status=not_run", headers=h))
    check(await client.get(f"/v1/test-cases/{case_id}", headers=h))
    assert (
        check(await client.get("/v1/test-cases/tc_01ARZ3NDEKTSV4RRFFQ69G5FAV", headers=h)).status_code == 404
    )
    patched = check(await client.patch(f"/v1/test-cases/{case_id}", json={"name": "Secrets"}, headers=h))
    assert patched.json()["name"] == "Secrets"
    assert (
        check(
            await client.patch(f"/v1/test-cases/{case_id}", json={"category": "nope"}, headers=h)
        ).status_code
        == 422
    )
    other = check(
        await client.post("/v1/test-cases", json={**body, "user_prompt": "Other"}, headers=h)
    ).json()
    clash = await client.patch(
        f"/v1/test-cases/{other['test_case_id']}", json={"user_prompt": "Tell me a secret"}, headers=h
    )
    assert check(clash).status_code == 409
    assert (
        check(
            await client.patch("/v1/test-cases/tc_01ARZ3NDEKTSV4RRFFQ69G5FAV", json={"name": "x"}, headers=h)
        ).status_code
        == 404
    )

    imported = check(
        await client.post(
            "/v1/test-cases/import",
            json={
                "agent_id": a,
                "test_cases": [{"user_prompt": "Hi"}, {"user_prompt": "A", "expected_behaviour": "B"}],
            },
            headers=h,
        )
    )
    assert imported.json()["created"] == 1 and imported.json()["errors"][0]["index"] == 0
    too_many = await client.post(
        "/v1/test-cases/import", json={"agent_id": a, "test_cases": [{}] * 501}, headers=h
    )
    assert check(too_many).status_code == 422
    check(await client.get(f"/v1/test-cases/export?agent_id={a}", headers=h))
    check(await client.get(f"/v1/test-cases/export?agent_id={a}&template=true", headers=h))

    drafts = check(
        await client.post(
            "/v1/test-cases/generate", json={"agent_id": a, "count": 2}, headers={**h, **idem()}
        )
    )
    assert len(drafts.json()["drafts"]) == 2
    from app.llms.adapters import fake

    original = fake.PURPOSE_REPLIES["test_case_generation"]
    fake.PURPOSE_REPLIES["test_case_generation"] = lambda m, s: "not json"
    try:
        down = await client.post("/v1/test-cases/generate", json={"agent_id": a}, headers={**h, **idem()})
        assert check(down).status_code == 503
    finally:
        fake.PURPOSE_REPLIES["test_case_generation"] = original

    assert check(await client.delete(f"/v1/test-cases/{case_id}", headers=h)).status_code == 204
    assert check(await client.delete(f"/v1/test-cases/{case_id}", headers=h)).status_code == 404


async def test_generate_without_credit_and_without_prompt(
    client: httpx.AsyncClient, account: Account, app: object
) -> None:
    from decimal import Decimal

    from app.billing import service as billing
    from tests.runtime_support import owner_sql

    h = account.headers
    agent = await make_agent(client, account)
    owner_sql(
        "update agents set draft_config = jsonb_set(draft_config, '{prompt}', '\"\"') where id = %s",
        (agent.agent_id,),
    )
    no_prompt = await client.post(
        "/v1/test-cases/generate", json={"agent_id": agent.agent_id}, headers={**h, **idem()}
    )
    assert check(no_prompt).status_code == 409
    funded = await make_agent(client, account)
    db = app.state.db  # type: ignore[attr-defined]
    async with db.transaction(workspace_id=account.workspace_id) as session:
        balance = await billing.get_balance(session, account.workspace_id)
        await billing.post_transaction(
            session,
            workspace_id=account.workspace_id,
            type="adjustment",
            amount_usd=-balance,
            description="t",
        )
        assert await billing.get_balance(session, account.workspace_id) == Decimal(0)
    broke = await client.post(
        "/v1/test-cases/generate", json={"agent_id": funded.agent_id}, headers={**h, **idem()}
    )
    assert check(broke).status_code == 402
