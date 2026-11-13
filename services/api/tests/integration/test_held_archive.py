"""Confirming or cancelling held archiving (022 US4, T071)."""

from __future__ import annotations

import httpx
from fastapi import FastAPI
from sqlalchemy import text

from app.knowledge.sources.fake_drive import FakeDriveClient
from tests.conftest import Account
from tests.connector_helpers import connect, documents, fake_drive, make_kb, node_id, sync_now, synced_source
from tests.contract.test_knowledge_contract import fake_embedder

__all__ = ["fake_drive", "fake_embedder"]


async def _folder(
    client: httpx.AsyncClient, account: Account, drive: FakeDriveClient, n: int
) -> tuple[str, dict]:
    root = drive.add_folder(f"F{n}")
    for i in range(n):
        drive.add_doc(root, f"Item {i:03d}", [f"Catalogue item {i} costs {i + 10} rupees per unit."])
    conn = await connect(client, account)
    kb_id = await make_kb(client, account, f"KB {n}")
    return kb_id, await synced_source(client, account, kb_id, conn["id"], root)


async def test_cancel_then_confirm(
    client: httpx.AsyncClient, app: FastAPI, account: Account, fake_drive: FakeDriveClient
) -> None:
    kb_id, source = await _folder(client, account, fake_drive, 20)
    base = f"/v1/knowledge-bases/{kb_id}/sources/{source['id']}/held-archive"
    for i in range(6):
        fake_drive.delete(node_id(fake_drive, f"Item {i:03d}"))
    await sync_now(app, source["id"])
    cancelled = await client.post(f"{base}/cancel", headers=account.headers)
    assert cancelled.status_code == 200 and cancelled.json()["state"] == "healthy"
    assert len(await documents(client, account, kb_id)) == 20
    await sync_now(app, source["id"])
    # One file comes back before the owner confirms: 5 of 20 are still over the allowance of 4,
    # so the hold stays, and confirming archives only the 5 still missing.
    fake_drive.nodes[node_id_of_trashed(fake_drive, "Item 000")].trashed = False
    await sync_now(app, source["id"])
    confirmed = await client.post(f"{base}/confirm", headers=account.headers)
    assert confirmed.status_code == 200
    names = {d["display_name"] for d in await documents(client, account, kb_id, "archived")}
    assert names == {f"Item {i:03d}" for i in range(1, 6)}
    again = await client.post(f"{base}/confirm", headers=account.headers)
    assert again.status_code == 409 and again.json()["code"] == "nothing_held"
    async with app.state.db.transaction(workspace_id=account.workspace_id) as session:
        actions = [r[0] for r in (await session.execute(text("select action from connector_activity"))).all()]
    assert "held_archive_cancelled" in actions and "held_archive_confirmed" in actions


def node_id_of_trashed(drive: FakeDriveClient, name: str) -> str:
    return next(n.id for n in drive.nodes.values() if n.name == name)


async def test_small_sources_archive_two_without_asking(
    client: httpx.AsyncClient, app: FastAPI, account: Account, fake_drive: FakeDriveClient
) -> None:
    kb_id, source = await _folder(client, account, fake_drive, 8)
    for i in range(2):
        fake_drive.delete(node_id(fake_drive, f"Item {i:03d}"))
    await sync_now(app, source["id"])
    assert len(await documents(client, account, kb_id, "archived")) == 2
    assert len(await documents(client, account, kb_id)) == 6
