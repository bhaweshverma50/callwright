"""Contract tests for contracts/datasets.yaml (008 T074)."""

from __future__ import annotations

import httpx

from tests.conftest import Account
from tests.contract.conftest import check
from tests.runtime_support import idem
from tests.sim_support import SimEnv, make_agent, seed_live_call

DS = "ds_01ARZ3NDEKTSV4RRFFQ69G5FAV"


async def test_every_dataset_operation(sim_env: SimEnv, client: httpx.AsyncClient, account: Account) -> None:
    h = account.headers
    agent = await make_agent(client, account)
    calls = [seed_live_call(account.workspace_id, agent) for _ in range(2)]
    created = check(
        await client.post(
            "/v1/datasets", json={"name": "Suite", "agent_id": agent.agent_id, "call_ids": calls}, headers=h
        )
    )
    assert created.status_code == 201 and created.json()["add_result"]["added"] == 2
    d = created.json()["dataset_id"]
    assert (
        check(
            await client.post("/v1/datasets", json={"name": "SUITE", "agent_id": agent.agent_id}, headers=h)
        ).status_code
        == 409
    )
    assert check(await client.post("/v1/datasets", json={"name": ""}, headers=h)).status_code == 422
    check(await client.get("/v1/datasets", headers=h))
    check(await client.get(f"/v1/datasets/{d}", headers=h))
    check(await client.patch(f"/v1/datasets/{d}", json={"description": None}, headers=h))
    other = check(
        await client.post("/v1/datasets", json={"name": "Other", "agent_id": agent.agent_id}, headers=h)
    ).json()
    assert (
        check(
            await client.patch(f"/v1/datasets/{other['dataset_id']}", json={"name": "suite"}, headers=h)
        ).status_code
        == 409
    )
    assert check(await client.patch(f"/v1/datasets/{d}", json={}, headers=h)).status_code == 422
    assert check(await client.patch(f"/v1/datasets/{DS}", json={"name": "x"}, headers=h)).status_code == 404
    check(await client.get(f"/v1/datasets/{d}/items", headers=h))
    assert check(await client.get(f"/v1/datasets/{DS}/items", headers=h)).status_code == 404
    added = check(await client.post(f"/v1/datasets/{d}/items", json={"call_ids": ["call_nope"]}, headers=h))
    assert added.json()["invalid"] == [{"call_id": "call_nope", "reason": "not_found"}]
    assert (
        check(await client.post(f"/v1/datasets/{DS}/items", json={"call_ids": calls}, headers=h)).status_code
        == 404
    )
    evaluated = check(await client.post(f"/v1/datasets/{d}/evaluate", headers={**h, **idem()}))
    assert evaluated.status_code == 202
    assert check(await client.post(f"/v1/datasets/{DS}/evaluate", headers={**h, **idem()})).status_code == 404
    assert check(await client.delete(f"/v1/datasets/{d}/items/{calls[0]}", headers=h)).status_code == 204
    assert check(await client.delete(f"/v1/datasets/{d}/items/{calls[0]}", headers=h)).status_code == 404
    assert check(await client.delete(f"/v1/datasets/{d}", headers=h)).status_code == 204
    assert check(await client.get(f"/v1/datasets/{d}", headers=h)).status_code == 404
    assert check(await client.delete(f"/v1/datasets/{d}", headers=h)).status_code == 404
