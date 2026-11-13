"""Synced knowledge stays with the agents it is attached to (022 SC-005, T036; SC-004 calls never
reach Drive)."""

from __future__ import annotations

import httpx
from fastapi import FastAPI

from app.knowledge.sources.fake_drive import FakeDriveClient
from tests.agent_helpers import create_ok
from tests.conftest import Account
from tests.connector_helpers import connect, fake_drive, make_kb, synced_source
from tests.contract.test_knowledge_contract import fake_embedder

__all__ = ["fake_drive", "fake_embedder"]


async def _call_for(client: httpx.AsyncClient, account: Account, agent_id: str, kb_id: str) -> str:
    from tests.runtime_support import insert_call, owner_sql

    await client.put(
        f"/v1/agents/{agent_id}/knowledge-bases", json={"kb_ids": [kb_id]}, headers=account.headers
    )
    detail = (await client.get(f"/v1/agents/{agent_id}", headers=account.headers)).json()
    call_id = insert_call(account.workspace_id, status="in_progress")
    owner_sql(
        "update calls set agent_id = %s, agent_version_id = %s where id = %s",
        (agent_id, detail["draft_version"]["id"], call_id),
    )
    return call_id


async def test_each_agent_searches_only_its_own_synced_knowledge(
    client: httpx.AsyncClient, app: FastAPI, account: Account, fake_drive: FakeDriveClient
) -> None:
    clinic_root = fake_drive.seed("clinic")["Clinic policies"]
    property_root = fake_drive.seed("property")["Listings"]
    conn = await connect(client, account)
    clinic_kb = await make_kb(client, account, "Clinic policies")
    property_kb = await make_kb(client, account, "Property listings")
    await synced_source(client, account, clinic_kb, conn["id"], clinic_root)
    await synced_source(client, account, property_kb, conn["id"], property_root)
    clinic_agent = await create_ok(client, account)
    property_agent = await create_ok(client, account)
    clinic_call = await _call_for(client, account, clinic_agent["id"], clinic_kb)
    property_call = await _call_for(client, account, property_agent["id"], property_kb)
    service = {"Authorization": f"Bearer {app.state.settings.service_token.get_secret_value()}"}
    calls_before = fake_drive.calls

    found = await client.post(
        "/v1/internal/knowledge/search",
        json={
            "call_id": clinic_call,
            "query": "cancelled with less than 24 hours notice fee",
            "kb_ids": [clinic_kb],
        },
        headers=service,
    )
    assert found.status_code == 200
    assert found.json()["results"] and {r["kb_id"] for r in found.json()["results"]} == {clinic_kb}

    own = await client.post(
        "/v1/internal/knowledge/search",
        json={
            "call_id": property_call,
            "query": "cancelled with less than 24 hours notice fee",
            "kb_ids": [property_kb],
        },
        headers=service,
    )
    assert own.status_code == 200 and {r["kb_id"] for r in own.json()["results"]} <= {property_kb}
    refused = await client.post(
        "/v1/internal/knowledge/search",
        json={"call_id": property_call, "query": "cancellation fee", "kb_ids": [clinic_kb]},
        headers=service,
    )
    assert refused.status_code == 403
    assert fake_drive.calls == calls_before


async def test_simulations_search_the_synced_copy_like_calls(
    client: httpx.AsyncClient, app: FastAPI, account: Account, fake_drive: FakeDriveClient
) -> None:
    """FR-019 (T091): a test run (008) searches synced documents exactly as a live call does, and
    never reaches Drive."""
    from app.core.ids import new_id
    from app.test_runs.models import TestRun

    root = fake_drive.seed("clinic")["Clinic policies"]
    conn = await connect(client, account)
    kb_id = await make_kb(client, account, "Clinic policies")
    other_kb = await make_kb(client, account, "Unattached")
    await synced_source(client, account, kb_id, conn["id"], root)
    agent = await create_ok(client, account)
    run_id = new_id("trn")
    async with app.state.db.transaction(workspace_id=account.workspace_id) as session:
        session.add(
            TestRun(
                id=run_id,
                workspace_id=account.workspace_id,
                agent_id=agent["id"],
                number=1,
                target_type="draft",
                config_snapshot={"kb_ids": [kb_id]},
                config_hash="x",
                agent_model="gpt-5.1",
                judge_model="gpt-5.1",
            )
        )
    service = {"Authorization": f"Bearer {app.state.settings.service_token.get_secret_value()}"}
    calls_before = fake_drive.calls
    found = await client.post(
        "/v1/internal/knowledge/search",
        json={"call_id": run_id, "query": "free parking basement two hours", "kb_ids": [kb_id]},
        headers=service,
    )
    assert found.status_code == 200 and found.json()["results"]
    refused = await client.post(
        "/v1/internal/knowledge/search",
        json={"call_id": run_id, "query": "free parking", "kb_ids": [other_kb]},
        headers=service,
    )
    assert refused.status_code == 403
    assert fake_drive.calls == calls_before
