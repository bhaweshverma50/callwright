"""contracts/flows.yaml: GET /calls/{call_id}/flow-transitions (004 T046)."""

from __future__ import annotations

import json

import httpx
from fastapi import FastAPI

from tests.conftest import Account, signup
from tests.contract.conftest import check
from tests.runtime_support import insert_call, owner_sql


async def test_ordered_items_and_empty_and_404(
    client: httpx.AsyncClient, app: FastAPI, account: Account
) -> None:
    call_id = insert_call(account.workspace_id)
    for seq, (to, trigger) in enumerate([("n_triage01", "always"), ("n_route001", "llm_condition")], start=1):
        payload = {
            "from_node_id": "n_start001",
            "to_node_id": to,
            "trigger": trigger,
            "turn_index": seq,
            "t_ms": seq * 1000,
        }
        owner_sql(
            "insert into call_events (workspace_id, call_id, seq, type, occurred_at, payload)"
            " values (%s,%s,%s,'flow_transition',now(),%s::jsonb)",
            (account.workspace_id, call_id, seq, json.dumps(payload)),
        )
    response = check(await client.get(f"/v1/calls/{call_id}/flow-transitions", headers=account.headers))
    assert [i["seq"] for i in response.json()["items"]] == [1, 2]
    empty = check(
        await client.get(
            f"/v1/calls/{insert_call(account.workspace_id)}/flow-transitions", headers=account.headers
        )
    )
    assert empty.json() == {"items": []}
    other = await signup(client, app)
    assert (
        check(await client.get(f"/v1/calls/{call_id}/flow-transitions", headers=other.headers)).status_code
        == 404
    )
