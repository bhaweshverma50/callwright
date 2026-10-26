"""Flow assistant (004 T086; US5, FR-036 to FR-039) with the deterministic fake model."""

from __future__ import annotations

import httpx

from tests.conftest import Account
from tests.flow_helpers import create_flow
from tests.runtime_support import owner_sql


def _charges(workspace_id: str) -> int:
    rows = owner_sql(
        "select count(*) from usage_events where workspace_id = %s and feature_key = 'flow_assistant'",
        (workspace_id,),
    )
    return int(rows[0][0])


async def _ask(
    client: httpx.AsyncClient, account: Account, flow: dict, text: str, **extra: object
) -> httpx.Response:
    body = {"messages": [{"role": "user", "content": text}], "base_revision": flow["revision"], **extra}
    return await client.post(f"/v1/flows/{flow['id']}/assistant", json=body, headers=account.headers)


async def test_proposal_is_validated_placed_and_charged_once(
    client: httpx.AsyncClient, account: Account
) -> None:
    flow = (await create_flow(client, account))["flow"]
    response = await _ask(
        client, account, flow, "Add a step that collects the caller's date of birth before ending"
    )
    assert response.status_code == 200, response.text
    body = response.json()
    kinds = [o["op"] for o in body["operations"]]
    assert kinds.count("add_node") == 1 and kinds.count("remove_edge") == 1 and kinds.count("add_edge") == 2
    assert [i for i in body["issues"] if i["severity"] == "error"] == []
    added = next(o["node"] for o in body["operations"] if o["op"] == "add_node")
    assert added["id"].startswith("n_") and added["config"]["overrides"]["llm"] is None
    existing = {n["id"]: n["position"] for n in flow["graph"]["nodes"]}
    for node in body["proposed_graph"]["nodes"]:
        if node["id"] in existing:
            assert node["position"] == existing[node["id"]]
    assert float(body["usage"]["cost_usd"]) >= 0
    assert _charges(account.workspace_id) == 1
    # Nothing was saved.
    unchanged = (await client.get(f"/v1/flows/{flow['id']}", headers=account.headers)).json()
    assert unchanged["revision"] == 1 and unchanged["graph"] == flow["graph"]


async def test_timeout_is_not_charged(client: httpx.AsyncClient, account: Account) -> None:
    flow = (await create_flow(client, account))["flow"]
    response = await _ask(client, account, flow, "add a billing transfer [timeout]")
    assert response.status_code == 504 and response.json()["code"] == "assistant_timeout"
    assert _charges(account.workspace_id) == 0


async def test_stale_base_revision_conflicts(client: httpx.AsyncClient, account: Account) -> None:
    flow = (await create_flow(client, account))["flow"]
    response = await _ask(client, account, {**flow, "revision": 7}, "add a step")
    assert response.status_code == 409 and response.json()["current_revision"] == 1
    assert _charges(account.workspace_id) == 0


async def test_unsaved_graph_is_used_when_sent(client: httpx.AsyncClient, account: Account) -> None:
    flow = (await create_flow(client, account))["flow"]
    graph = flow["graph"]
    graph["nodes"][1]["label"] = "Reception"
    response = await _ask(client, account, flow, "Send billing questions to a human", graph=graph)
    assert response.status_code == 200
    proposed = response.json()["proposed_graph"]
    assert any(n["label"] == "Reception" for n in proposed["nodes"])
    assert any(n["type"] == "transfer" for n in proposed["nodes"])
