"""No credit pauses scheduled syncs, never searches (022 US4, T072; FR-024)."""

from __future__ import annotations

from decimal import Decimal

import httpx
from fastapi import FastAPI

from app.billing import service as billing
from app.knowledge.sources.fake_drive import FakeDriveClient
from tests.conftest import Account
from tests.connector_helpers import connect, fake_drive, make_kb, search, sync_now, synced_source
from tests.contract.test_knowledge_contract import fake_embedder

__all__ = ["fake_drive", "fake_embedder"]


async def _set_balance(app: FastAPI, workspace_id: str, target: Decimal) -> None:
    async with app.state.db.transaction(workspace_id=workspace_id) as session:
        delta = target - await billing.get_balance(session, workspace_id)
        if delta:
            await billing.post_transaction(
                session, workspace_id=workspace_id, type="adjustment", amount_usd=delta, description="test"
            )


async def test_no_credit_pauses_scheduled_syncs(
    client: httpx.AsyncClient, app: FastAPI, account: Account, fake_drive: FakeDriveClient
) -> None:
    root = fake_drive.seed("property")["Listings"]
    conn = await connect(client, account)
    kb_id = await make_kb(client, account)
    source = await synced_source(client, account, kb_id, conn["id"], root)
    await _set_balance(app, account.workspace_id, Decimal("0"))
    assert await sync_now(app, source["id"], "scheduled") is None
    after = (
        await client.get(f"/v1/knowledge-bases/{kb_id}/sources/{source['id']}", headers=account.headers)
    ).json()
    assert after["state"] == "needs_attention" and after["attention_reason"] == "no_credit"
    manual = await client.post(
        f"/v1/knowledge-bases/{kb_id}/sources/{source['id']}/sync", headers=account.headers
    )
    assert manual.status_code == 402
    other = await make_kb(client, account, "Other")
    create = await client.post(
        f"/v1/knowledge-bases/{other}/sources",
        json={"connection_id": conn["id"], "root_kind": "folder", "root_id": root},
        headers=account.headers,
    )
    assert create.status_code == 402
    assert await search(client, account, kb_id, "bedroom flat in Pune rent")
    await _set_balance(app, account.workspace_id, Decimal("5"))
    assert await sync_now(app, source["id"], "scheduled")
    healed = (
        await client.get(f"/v1/knowledge-bases/{kb_id}/sources/{source['id']}", headers=account.headers)
    ).json()
    assert healed["state"] == "healthy"
