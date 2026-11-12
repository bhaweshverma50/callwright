"""A bad sync never loses knowledge (022 US4, T070, T073; SC-003, research R6)."""

from __future__ import annotations

import httpx
from fastapi import FastAPI

from app.knowledge.sources.fake_drive import FakeDriveClient
from tests.conftest import Account
from tests.connector_helpers import (
    connect,
    documents,
    fake_drive,
    make_kb,
    node_id,
    run_of,
    search,
    sync_now,
    synced_source,
)
from tests.contract.test_knowledge_contract import fake_embedder

__all__ = ["fake_drive", "fake_embedder"]


async def _big(
    client: httpx.AsyncClient, account: Account, drive: FakeDriveClient, n: int = 20
) -> tuple[str, dict]:
    root = drive.add_folder("Notes")
    for i in range(n):
        drive.add_doc(root, f"Note {i:02d}", [f"Front desk note {i}: the procedure code is {i * 37}."])
    conn = await connect(client, account)
    kb_id = await make_kb(client, account)
    return kb_id, await synced_source(client, account, kb_id, conn["id"], root)


async def _source(client: httpx.AsyncClient, account: Account, kb_id: str, source_id: str) -> dict:
    response = await client.get(f"/v1/knowledge-bases/{kb_id}/sources/{source_id}", headers=account.headers)
    return dict(response.json())


async def test_revoked_access_changes_nothing(
    client: httpx.AsyncClient, app: FastAPI, account: Account, fake_drive: FakeDriveClient
) -> None:
    kb_id, source = await _big(client, account, fake_drive)
    fake_drive.revoked = True
    run = await run_of(client, account, kb_id, source["id"], str(await sync_now(app, source["id"])))
    assert run["status"] == "failed" and run["failure_reason"] == "connection_revoked"
    assert len(await documents(client, account, kb_id)) == 20
    after = await _source(client, account, kb_id, source["id"])
    assert after["state"] == "needs_attention" and after["attention_reason"] == "access_lost"
    conn = (await client.get(f"/v1/connections/{source['connection_id']}", headers=account.headers)).json()
    assert conn["health"] == "revoked"
    assert await search(client, account, kb_id, "front desk note procedure code")


async def test_unshared_folder_changes_nothing(
    client: httpx.AsyncClient, app: FastAPI, account: Account, fake_drive: FakeDriveClient
) -> None:
    kb_id, source = await _big(client, account, fake_drive)
    fake_drive.unshared.add(source["root_id"])
    run = await run_of(client, account, kb_id, source["id"], str(await sync_now(app, source["id"])))
    assert run["failure_reason"] == "access_lost" and run["counts"]["archived"] == 0
    assert len(await documents(client, account, kb_id)) == 20
    assert (await _source(client, account, kb_id, source["id"]))["attention_reason"] == "access_lost"


async def test_emptied_folder_and_half_removed_are_held(
    client: httpx.AsyncClient, app: FastAPI, account: Account, fake_drive: FakeDriveClient
) -> None:
    kb_id, source = await _big(client, account, fake_drive)
    for i in range(10):
        fake_drive.delete(node_id(fake_drive, f"Note {i:02d}"))
    run = await run_of(client, account, kb_id, source["id"], str(await sync_now(app, source["id"])))
    assert run["status"] == "held" and run["counts"]["held_back"] == 10 and run["counts"]["archived"] == 0
    for i in range(10, 20):
        fake_drive.delete(node_id(fake_drive, f"Note {i:02d}"))
    run = await run_of(client, account, kb_id, source["id"], str(await sync_now(app, source["id"])))
    assert run["status"] == "held" and run["counts"]["held_back"] == 20
    assert len(await documents(client, account, kb_id)) == 20
    held = await _source(client, account, kb_id, source["id"])
    assert held["attention_message"] == "This sync would archive 20 of 20 documents"


async def test_outage_and_partial_listing_apply_nothing(
    client: httpx.AsyncClient, app: FastAPI, account: Account, fake_drive: FakeDriveClient
) -> None:
    kb_id, source = await _big(client, account, fake_drive)
    for i in range(5):
        fake_drive.delete(node_id(fake_drive, f"Note {i:02d}"))
    fake_drive.outage = True
    run = await run_of(client, account, kb_id, source["id"], str(await sync_now(app, source["id"])))
    assert run["failure_reason"] == "google_unavailable"
    fake_drive.outage = False
    fake_drive.fail_after_items = 3
    run = await run_of(client, account, kb_id, source["id"], str(await sync_now(app, source["id"])))
    assert run["failure_reason"] == "google_unavailable" and run["counts"]["archived"] == 0
    assert len(await documents(client, account, kb_id)) == 20
    assert (await _source(client, account, kb_id, source["id"]))["state"] == "healthy"
    fake_drive.fail_after_items = None
    run = await run_of(client, account, kb_id, source["id"], str(await sync_now(app, source["id"])))
    assert run["status"] == "held"  # 5 of 20 is over the allowance of 4


async def test_too_large_folder_fails_before_applying(
    client: httpx.AsyncClient, app: FastAPI, account: Account, fake_drive: FakeDriveClient
) -> None:
    kb_id, source = await _big(client, account, fake_drive, n=6)
    fake_drive.delete(node_id(fake_drive, "Note 00"))
    fake_drive.item_cap = 4
    run = await run_of(client, account, kb_id, source["id"], str(await sync_now(app, source["id"])))
    assert run["failure_reason"] == "source_too_large" and run["counts"]["archived"] == 0
    after = await _source(client, account, kb_id, source["id"])
    assert after["attention_reason"] == "source_too_large"
    assert len(await documents(client, account, kb_id)) == 6


async def test_reconnect_resumes_sources(
    client: httpx.AsyncClient, app: FastAPI, account: Account, fake_drive: FakeDriveClient
) -> None:
    from tests.connector_helpers import complete, start

    kb_id, source = await _big(client, account, fake_drive, n=3)
    fake_drive.revoked = True
    await sync_now(app, source["id"])
    fake_drive.revoked = False
    healed = await complete(client, account, await start(client, account, source["connection_id"]))
    assert healed.status_code == 200
    after = await _source(client, account, kb_id, source["id"])
    assert after["state"] == "pending"
