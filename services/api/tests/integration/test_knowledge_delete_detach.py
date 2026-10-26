"""Deleting an attached knowledge base (005 T071): drafts are detached, and a published version
that still lists it gets no results from it."""

from __future__ import annotations

import httpx
from fastapi import FastAPI

from tests.agent_helpers import create_ok
from tests.conftest import Account
from tests.contract.test_knowledge_contract import fake_embedder, ready_kb  # noqa: F401
from tests.runtime_support import insert_call, owner_sql


async def test_delete_detaches_and_published_gets_nothing(
    client: httpx.AsyncClient, account: Account, app: FastAPI
) -> None:
    agent = await create_ok(client, account)
    kb = await ready_kb(client, account)
    await client.put(
        f"/v1/agents/{agent['id']}/knowledge-bases", json={"kb_ids": [kb["id"]]}, headers=account.headers
    )
    detail = (await client.get(f"/v1/agents/{agent['id']}", headers=account.headers)).json()
    version_id = detail["draft_version"]["id"]
    await client.put(
        f"/v1/agents/{agent['id']}/published-version",
        json={"version_id": version_id},
        headers=account.headers,
    )
    call_id = insert_call(account.workspace_id, status="in_progress")
    owner_sql(
        "update calls set agent_id = %s, agent_version_id = %s where id = %s",
        (agent["id"], version_id, call_id),
    )
    service = {"Authorization": f"Bearer {app.state.settings.service_token.get_secret_value()}"}
    body = {"call_id": call_id, "query": "refund within how many days", "kb_ids": [kb["id"]]}
    before = await client.post("/v1/internal/knowledge/search", json=body, headers=service)
    assert before.json()["results"]

    deleted = await client.delete(f"/v1/knowledge-bases/{kb['id']}?confirm=true", headers=account.headers)
    assert deleted.json()["detached_agent_ids"] == [agent["id"]]
    after = (await client.get(f"/v1/agents/{agent['id']}", headers=account.headers)).json()
    assert after["draft_config"]["kb_ids"] == []
    assert after["published_version"]["id"] == version_id
    gone = await client.post("/v1/internal/knowledge/search", json=body, headers=service)
    assert gone.status_code == 200 and gone.json()["results"] == []
