"""Staying in step with Drive (022 US3, T054): edits, renames, removals and additions, the old
version serving until the new one is ready, archive and restore, moves between sources."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
from fastapi import FastAPI
from sqlalchemy import text

from app.knowledge.sources import jobs as sync_jobs
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


async def _clinic(client: httpx.AsyncClient, account: Account, drive: FakeDriveClient) -> tuple[str, dict]:
    root = drive.seed("clinic")["Clinic policies"]
    conn = await connect(client, account)
    kb_id = await make_kb(client, account)
    return kb_id, await synced_source(client, account, kb_id, conn["id"], root)


async def test_edit_rename_delete_add(
    client: httpx.AsyncClient, app: FastAPI, account: Account, fake_drive: FakeDriveClient
) -> None:
    kb_id, source = await _clinic(client, account, fake_drive)
    root = source["root_id"]
    fake_drive.edit(node_id(fake_drive, "Clinic hours"), ["The clinic now opens at 8 am on weekdays."])
    fake_drive.rename(node_id(fake_drive, "Parking.pdf"), "Parking and transport.pdf")
    fake_drive.delete(node_id(fake_drive, "Pharmacy.docx"))
    fake_drive.add_doc(root, "Telehealth", ["Video consultations are available every evening."])
    run_id = await sync_now(app, source["id"])
    assert run_id
    run = await run_of(client, account, kb_id, source["id"], run_id)
    assert run["counts"] | {} == {
        "added": 1,
        "updated": 1,
        "unchanged": 7,
        "renamed": 1,
        "archived": 1,
        "held_back": 0,
        "skipped": 2,
        "failed": 0,
    }
    names = {d["display_name"] for d in await documents(client, account, kb_id)}
    assert "Parking and transport.pdf" in names and "Telehealth" in names and "Pharmacy.docx" not in names
    assert [d["display_name"] for d in await documents(client, account, kb_id, "archived")] == [
        "Pharmacy.docx"
    ]
    assert any(
        "8 am" in r["content"] for r in await search(client, account, kb_id, "clinic opens 8 am weekdays")
    )


async def test_unchanged_and_metadata_only_syncs_process_nothing(
    client: httpx.AsyncClient, app: FastAPI, account: Account, fake_drive: FakeDriveClient
) -> None:
    kb_id, source = await _clinic(client, account, fake_drive)
    before = {d["id"] for d in await documents(client, account, kb_id)}
    calls = fake_drive.calls
    run = await run_of(client, account, kb_id, source["id"], str(await sync_now(app, source["id"])))
    assert run["counts"]["unchanged"] == 10 and run["counts"]["updated"] == 0
    assert fake_drive.calls - calls == 3  # refresh, root, listing: no downloads
    fake_drive.touch(node_id(fake_drive, "Our doctors"))
    run = await run_of(client, account, kb_id, source["id"], str(await sync_now(app, source["id"])))
    assert run["counts"]["updated"] == 0 and run["counts"]["unchanged"] == 10
    assert {d["id"] for d in await documents(client, account, kb_id)} == before


async def test_failed_new_version_keeps_the_old_one(
    client: httpx.AsyncClient, app: FastAPI, account: Account, fake_drive: FakeDriveClient
) -> None:
    kb_id, source = await _clinic(client, account, fake_drive)
    doc_node = node_id(fake_drive, "Insurance")
    fake_drive.edit(doc_node, ["We now also accept Niva Bupa insurance cards."])
    fake_drive.corrupt.add(doc_node)
    await sync_now(app, source["id"])
    docs = await documents(client, account, kb_id)
    insurance = [d for d in docs if d["display_name"] == "Insurance"]
    assert len(insurance) == 1 and insurance[0]["status"] == "ready"
    assert any(
        "Star Health" in r["content"]
        for r in await search(client, account, kb_id, "Star Health insurance cards")
    )


async def test_restore_keeps_and_archive_action(
    client: httpx.AsyncClient, app: FastAPI, account: Account, fake_drive: FakeDriveClient
) -> None:
    kb_id, source = await _clinic(client, account, fake_drive)
    fake_drive.delete(node_id(fake_drive, "Lab tests"))
    await sync_now(app, source["id"])
    [archived] = await documents(client, account, kb_id, "archived")
    restored = await client.post(
        f"/v1/knowledge-bases/{kb_id}/documents/{archived['id']}/restore", headers=account.headers
    )
    assert restored.status_code == 200 and restored.json()["status"] == "ready"
    await sync_now(app, source["id"])
    assert archived["id"] in {d["id"] for d in await documents(client, account, kb_id)}
    again = await client.post(
        f"/v1/knowledge-bases/{kb_id}/documents/{archived['id']}/restore", headers=account.headers
    )
    assert again.status_code == 409 and again.json()["code"] == "not_archived"
    other = (await documents(client, account, kb_id))[0]
    refused = await client.post(
        f"/v1/knowledge-bases/{kb_id}/documents/{other['id']}/archive", headers=account.headers
    )
    assert refused.status_code == 409 and refused.json()["code"] == "not_kept"
    archived_now = await client.post(
        f"/v1/knowledge-bases/{kb_id}/documents/{archived['id']}/archive", headers=account.headers
    )
    assert archived_now.status_code == 200 and archived_now.json()["status"] == "archived"


async def test_a_file_that_comes_back_is_restored_without_processing(
    client: httpx.AsyncClient, app: FastAPI, account: Account, fake_drive: FakeDriveClient
) -> None:
    kb_id, source = await _clinic(client, account, fake_drive)
    node = node_id(fake_drive, "Clinic hours")
    fake_drive.delete(node)
    await sync_now(app, source["id"])
    fake_drive.nodes[node].trashed = False
    run = await run_of(client, account, kb_id, source["id"], str(await sync_now(app, source["id"])))
    assert run["counts"]["added"] == 0
    assert "Clinic hours" in {d["display_name"] for d in await documents(client, account, kb_id)}


async def test_purge_deletes_documents_archived_over_30_days_ago(
    client: httpx.AsyncClient, app: FastAPI, account: Account, fake_drive: FakeDriveClient
) -> None:
    kb_id, source = await _clinic(client, account, fake_drive)
    fake_drive.delete(node_id(fake_drive, "Lab tests"))
    await sync_now(app, source["id"])
    [archived] = await documents(client, account, kb_id, "archived")
    async with app.state.db.transaction(workspace_id=account.workspace_id) as session:
        await session.execute(
            text("update kb_documents set archived_at = :t where id = :id"),
            {"t": datetime.now(UTC) - timedelta(days=31), "id": archived["id"]},
        )
    assert await sync_jobs.purge_archived(app.state.db, app.state.storage) >= 1
    assert await documents(client, account, kb_id, "archived") == []


async def test_move_between_two_sources_keeps_one_document(
    client: httpx.AsyncClient, app: FastAPI, account: Account, fake_drive: FakeDriveClient
) -> None:
    a = fake_drive.add_folder("A")
    b = fake_drive.add_folder("B")
    node = fake_drive.add_pdf(a, "Visiting.pdf", ["Visiting hours are 4 pm to 7 pm."])
    conn = await connect(client, account)
    kb_id = await make_kb(client, account)
    src_a = await synced_source(client, account, kb_id, conn["id"], a)
    src_b = await synced_source(client, account, kb_id, conn["id"], b)
    [doc] = await documents(client, account, kb_id)
    fake_drive.move(node, b)
    # B syncs first: the file is waiting as a duplicate; then A hands the document over.
    await sync_now(app, src_b["id"])
    await sync_now(app, src_a["id"])
    docs = await documents(client, account, kb_id)
    assert [d["id"] for d in docs] == [doc["id"]] and docs[0]["source"]["source_id"] == src_b["id"]
    assert await documents(client, account, kb_id, "archived") == []
    # And back again, A first this time: archived by A, restored by B's... A's next sync.
    fake_drive.move(node, a)
    await sync_now(app, src_b["id"])
    await sync_now(app, src_a["id"])
    docs = await documents(client, account, kb_id)
    assert [d["id"] for d in docs] == [doc["id"]] and docs[0]["source"]["source_id"] == src_a["id"]
