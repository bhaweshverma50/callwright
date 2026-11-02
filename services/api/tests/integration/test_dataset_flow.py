"""US5 end to end (008 T076): create, add with duplicates and a wrong agent, remove, evaluate,
delete keeps the calls, and a batch from a dataset records it."""

from __future__ import annotations

import httpx

from tests.conftest import Account
from tests.runtime_support import idem, owner_sql
from tests.sim_support import SimEnv, make_agent, seed_live_call


async def test_datasets_end_to_end(sim_env: SimEnv, client: httpx.AsyncClient, account: Account) -> None:
    h = account.headers
    ws = account.workspace_id
    agent = await make_agent(client, account)
    other = await make_agent(client, account)
    calls = [seed_live_call(ws, agent) for _ in range(4)]

    created = await client.post(
        "/v1/datasets",
        json={"name": "Hard cases", "agent_id": agent.agent_id, "description": "Billing"},
        headers=h,
    )
    assert created.status_code == 201, created.text
    ds = created.json()
    assert ds["item_count"] == 0 and ds["agent_name"] == agent.body["name"]
    clash = await client.post(
        "/v1/datasets", json={"name": "hard cases", "agent_id": agent.agent_id}, headers=h
    )
    assert clash.status_code == 409 and clash.json()["errors"][0]["pointer"] == "/name"
    assert (await client.post("/v1/datasets", json={"name": "No agent"}, headers=h)).status_code == 422

    first = (
        await client.post(f"/v1/datasets/{ds['dataset_id']}/items", json={"call_ids": calls[:1]}, headers=h)
    ).json()
    assert first["added"] == 1
    foreign = seed_live_call(ws, other)
    result = (
        await client.post(
            f"/v1/datasets/{ds['dataset_id']}/items", json={"call_ids": [*calls[:4], foreign]}, headers=h
        )
    ).json()
    assert result == {
        "added": 3,
        "skipped_duplicates": 1,
        "skipped_invalid": 1,
        "invalid": [{"call_id": foreign, "reason": "wrong_agent"}],
    }
    items = (await client.get(f"/v1/datasets/{ds['dataset_id']}/items?page_size=2", headers=h)).json()
    assert items["total"] == 4 and len(items["items"]) == 2 and items["total_pages"] == 2
    assert all(i["available"] and i["call_status"] == "completed" for i in items["items"])

    assert (
        await client.delete(f"/v1/datasets/{ds['dataset_id']}/items/{calls[3]}", headers=h)
    ).status_code == 204
    assert (
        await client.delete(f"/v1/datasets/{ds['dataset_id']}/items/{calls[3]}", headers=h)
    ).status_code == 404
    assert (await client.get(f"/v1/datasets/{ds['dataset_id']}", headers=h)).json()["item_count"] == 3

    # Purged transcript: unavailable and skipped by bulk evaluate.
    owner_sql("update calls set transcript = null where id = %s", (calls[2],))
    listed = (await client.get(f"/v1/datasets/{ds['dataset_id']}/items", headers=h)).json()["items"]
    assert {i["call_id"]: i["available"] for i in listed}[calls[2]] is False
    evaluated = await client.post(
        f"/v1/datasets/{ds['dataset_id']}/evaluate", json={}, headers={**h, **idem()}
    )
    assert evaluated.status_code == 202, evaluated.text
    assert evaluated.json() == {"enqueued": 2, "skipped_up_to_date": 0, "skipped_unavailable": 1}
    await sim_env.drain()
    groups = owner_sql(
        "select count(*) from evaluator_run_groups where trigger = 'dataset' and call_id = any(%s)",
        (calls[:2],),
    )
    assert groups[0][0] == 2
    again = (
        await client.post(
            f"/v1/datasets/{ds['dataset_id']}/evaluate", json={"only_missing": True}, headers={**h, **idem()}
        )
    ).json()
    assert again["skipped_up_to_date"] == 2 and again["enqueued"] == 0

    renamed = await client.patch(
        f"/v1/datasets/{ds['dataset_id']}", json={"name": "Hard cases v2"}, headers=h
    )
    assert renamed.status_code == 200 and renamed.json()["name"] == "Hard cases v2"

    # A batch from the dataset uses its available calls and records where it came from.
    exp = await client.post(
        "/v1/experiments",
        json={"agent_id": agent.agent_id, "mode": "replay", "dataset_id": ds["dataset_id"]},
        headers={**h, **idem()},
    )
    assert exp.status_code == 202, exp.text
    assert exp.json()["source"] == "dataset" and exp.json()["dataset_id"] == ds["dataset_id"]
    assert exp.json()["total_count"] == 2
    wrong = await client.post(
        "/v1/experiments",
        json={"agent_id": other.agent_id, "mode": "replay", "dataset_id": ds["dataset_id"]},
        headers={**h, **idem()},
    )
    assert wrong.status_code == 422

    assert (await client.delete(f"/v1/datasets/{ds['dataset_id']}", headers=h)).status_code == 204
    assert owner_sql("select count(*) from calls where id = any(%s)", (calls,))[0][0] == 4
    assert (
        owner_sql("select count(*) from dataset_items where dataset_id = %s", (ds["dataset_id"],))[0][0] == 0
    )
    filtered = (await client.get(f"/v1/datasets?agent_id={agent.agent_id}", headers=h)).json()
    assert filtered["total"] == 0
