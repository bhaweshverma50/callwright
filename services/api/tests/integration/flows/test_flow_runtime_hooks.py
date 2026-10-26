"""Cross-feature hooks (004 T097, T098, research R16): draft test snapshots carry the compiled
flow, the transition projection, mock coverage and tool node usages."""

from __future__ import annotations

import json

import httpx
from fastapi import FastAPI

from app.agent_versions import service as versions
from app.flows import service
from tests.conftest import Account, signup
from tests.flow_helpers import clinic, create_flow, save
from tests.runtime_support import insert_call, owner_sql


async def test_draft_test_snapshot_runs_the_canvas(
    client: httpx.AsyncClient, app: FastAPI, account: Account
) -> None:
    flow = (await create_flow(client, account))["flow"]
    await save(client, account, flow, clinic())
    async with app.state.db.transaction(workspace_id=account.workspace_id) as session:
        version = await versions.snapshot_for_test(session, flow["agent_id"])
        block = version.config["flow"]
    assert block["compiled"]["entry_node_id"] == "n_start001"
    assert block["graph_hash"] == block["compiled"]["graph_hash"]


async def test_draft_with_errors_snapshots_without_compiled_flow(
    client: httpx.AsyncClient, app: FastAPI, account: Account
) -> None:
    flow = (await create_flow(client, account))["flow"]
    g = clinic()
    g["nodes"][4]["config"]["message"] = ""
    await save(client, account, flow, g)
    async with app.state.db.transaction(workspace_id=account.workspace_id) as session:
        version = await versions.snapshot_for_test(session, flow["agent_id"])
        agent = await versions.lock_agent(session, flow["agent_id"])
        blockers = await versions.current_blockers(session, agent, version)
    assert version.config["flow"]["compiled"] is None
    assert any(b["code"] == "flow_has_errors" for b in blockers)


async def test_transitions_projection(client: httpx.AsyncClient, app: FastAPI, account: Account) -> None:
    call_id = insert_call(account.workspace_id)
    payloads = [
        {
            "from_node_id": "n_start001",
            "from_label": "Start",
            "to_node_id": "n_triage01",
            "to_label": "Triage",
            "trigger": "always",
            "turn_index": 0,
            "t_ms": 10,
            "engine_ms": 2,
        },
        {
            "from_node_id": "n_triage01",
            "from_label": "Triage",
            "to_node_id": "n_end00001",
            "to_label": "End",
            "edge_id": "e_done0000",
            "edge_label": "Done",
            "trigger": "llm_condition",
            "function_name": "route_to_done",
            "turn_index": 2,
            "t_ms": 9000,
            "engine_ms": 3,
            "model_ms": 420,
        },
    ]
    for seq, payload in enumerate(payloads, start=1):
        owner_sql(
            "insert into call_events (workspace_id, call_id, seq, type, occurred_at, payload)"
            " values (%s,%s,%s,'flow_transition',now(),%s::jsonb)",
            (account.workspace_id, call_id, seq, json.dumps(payload)),
        )
    owner_sql(
        "insert into call_events (workspace_id, call_id, seq, type, occurred_at, payload)"
        " values (%s,%s,3,'warning',now(),'{}'::jsonb)",
        (account.workspace_id, call_id),
    )
    response = await client.get(f"/v1/calls/{call_id}/flow-transitions", headers=account.headers)
    assert response.status_code == 200
    items = response.json()["items"]
    assert [i["to_node_id"] for i in items] == ["n_triage01", "n_end00001"]
    assert items[1]["model_ms"] == 420 and items[1]["seq"] == 2
    other = await signup(client, app)
    assert (
        await client.get(f"/v1/calls/{call_id}/flow-transitions", headers=other.headers)
    ).status_code == 404
    empty = insert_call(account.workspace_id)
    assert (await client.get(f"/v1/calls/{empty}/flow-transitions", headers=account.headers)).json() == {
        "items": []
    }


async def test_mock_coverage_and_tool_usages(
    client: httpx.AsyncClient, app: FastAPI, account: Account
) -> None:
    flow = (await create_flow(client, account))["flow"]
    g = clinic()
    g["nodes"][3]["config"]["mock_response"] = None
    tool = await client.post(
        "/v1/tools",
        json={"type": "end_call", "name": "hang_up", "description": "End the call", "config": {}},
        headers=account.headers,
    )
    tool_id = tool.json()["id"]
    g["nodes"][1]["config"]["tool_ids"] = [tool_id]
    assert (await save(client, account, flow, g)).status_code == 200
    coverage = (
        await client.get(f"/v1/agents/{flow['agent_id']}/tools/mock-coverage", headers=account.headers)
    ).json()
    assert {"source": "flow_node", "node_id": "n_book0001", "name": "Book slot"} in coverage["missing"]
    async with app.state.db.transaction(workspace_id=account.workspace_id) as session:
        usages = await service.tool_node_usages(session, tool_id)
    assert usages == [{"agent_id": flow["agent_id"], "flow_id": flow["id"], "node_ids": ["n_triage01"]}]


async def test_tool_usages_list_flow_nodes(client: httpx.AsyncClient, account: Account) -> None:
    flow = (await create_flow(client, account))["flow"]
    tool = await client.post(
        "/v1/tools",
        json={"type": "end_call", "name": "wrap_up", "description": "End the call", "config": {}},
        headers=account.headers,
    )
    g = clinic()
    g["nodes"][1]["config"]["tool_ids"] = [tool.json()["id"]]
    assert (await save(client, account, flow, g)).status_code == 200
    usages = (await client.get(f"/v1/tools/{tool.json()['id']}/usages", headers=account.headers)).json()
    assert usages["items"] == [
        {
            "agent_id": flow["agent_id"],
            "agent_name": "Clinic intake",
            "in_draft": True,
            "published_version_ids": [],
            "flow_node_ids": ["n_triage01"],
        }
    ]
