"""Scheduling and one sync at a time (022 US3, T055; research R10)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
from fastapi import FastAPI
from sqlalchemy import text

from app.knowledge.sources import jobs as sync_jobs
from app.knowledge.sources.fake_drive import FakeDriveClient
from tests.conftest import Account
from tests.connector_helpers import connect, documents, fake_drive, make_kb, settle, synced_source
from tests.contract.test_knowledge_contract import fake_embedder

__all__ = ["fake_drive", "fake_embedder"]


async def _source(client: httpx.AsyncClient, account: Account, drive: FakeDriveClient) -> tuple[str, dict]:
    root = drive.seed("property")["Listings"]
    conn = await connect(client, account)
    kb_id = await make_kb(client, account)
    return kb_id, await synced_source(client, account, kb_id, conn["id"], root)


async def _set(app: FastAPI, account: Account, sql: str, **params: object) -> None:
    async with app.state.db.transaction(workspace_id=account.workspace_id) as session:
        await session.execute(text(sql), params)


async def test_due_sources_are_claimed_once(
    client: httpx.AsyncClient, app: FastAPI, account: Account, fake_drive: FakeDriveClient
) -> None:
    _, source = await _source(client, account, fake_drive)
    next_at = datetime.fromisoformat(source["next_sync_at"])
    assert timedelta(minutes=14) < next_at - datetime.now(UTC) <= timedelta(minutes=15)  # SC-001
    assert source["id"] not in {s for s, _ in await sync_jobs.due_sources(app.state.db)}
    await _set(
        app,
        account,
        "update kb_sources set next_sync_at = now() - interval '1 minute' where id = :id",
        id=source["id"],
    )
    assert source["id"] in {s for s, _ in await sync_jobs.due_sources(app.state.db)}
    assert source["id"] not in {s for s, _ in await sync_jobs.due_sources(app.state.db)}


async def test_sync_now_while_running_and_stale_runs(
    client: httpx.AsyncClient, app: FastAPI, account: Account, fake_drive: FakeDriveClient
) -> None:
    kb_id, source = await _source(client, account, fake_drive)
    url = f"/v1/knowledge-bases/{kb_id}/sources/{source['id']}/sync"
    await _set(
        app,
        account,
        "update kb_sources set running_run_id = :run, running_since = now() where id = :id",
        run=source["last_run"]["id"],
        id=source["id"],
    )
    busy = await client.post(url, headers=account.headers)
    assert busy.status_code == 409 and busy.json()["code"] == "sync_running"
    assert busy.json()["run"]["id"] == source["last_run"]["id"]
    await _set(
        app,
        account,
        "update kb_sources set running_since = now() - interval '31 minutes' where id = :id",
        id=source["id"],
    )
    started = await client.post(url, headers=account.headers)
    assert started.status_code == 202 and started.json()["trigger"] == "manual"
    await settle()
    detail = (
        await client.get(f"/v1/knowledge-bases/{kb_id}/sources/{source['id']}", headers=account.headers)
    ).json()
    assert detail["state"] == "healthy" and detail["last_run"]["status"] == "succeeded"


async def test_interval_changes_and_limits(
    client: httpx.AsyncClient, account: Account, fake_drive: FakeDriveClient
) -> None:
    kb_id, source = await _source(client, account, fake_drive)
    url = f"/v1/knowledge-bases/{kb_id}/sources/{source['id']}"
    changed = await client.patch(url, json={"interval_minutes": 60}, headers=account.headers)
    assert changed.status_code == 200
    gap = datetime.fromisoformat(changed.json()["next_sync_at"]) - datetime.fromisoformat(
        changed.json()["last_success_at"]
    )
    assert timedelta(minutes=59) < gap <= timedelta(minutes=60)
    for bad in (4, 1441):
        response = await client.patch(url, json={"interval_minutes": bad}, headers=account.headers)
        assert response.status_code == 422


async def test_remove_source_keep_or_archive(
    client: httpx.AsyncClient, app: FastAPI, account: Account, fake_drive: FakeDriveClient
) -> None:
    kb_id, source = await _source(client, account, fake_drive)
    kept = await client.delete(
        f"/v1/knowledge-bases/{kb_id}/sources/{source['id']}?documents=keep", headers=account.headers
    )
    assert kept.status_code == 204
    docs = await documents(client, account, kb_id)
    assert len(docs) == 5 and not any(d["managed"] for d in docs)
    deleted = await client.delete(
        f"/v1/knowledge-bases/{kb_id}/documents/{docs[0]['id']}", headers=account.headers
    )
    assert deleted.status_code == 204

    other_root = fake_drive.seed("clinic")["Clinic policies"]
    conn_id = source["connection_id"]
    second = await synced_source(client, account, kb_id, conn_id, other_root)
    archived = await client.delete(
        f"/v1/knowledge-bases/{kb_id}/sources/{second['id']}?documents=archive", headers=account.headers
    )
    assert archived.status_code == 204
    assert len(await documents(client, account, kb_id, "archived")) == 10
    missing = await client.delete(
        f"/v1/knowledge-bases/{kb_id}/sources/{second['id']}", headers=account.headers
    )
    assert missing.status_code in (404, 422)
    async with app.state.db.transaction(workspace_id=account.workspace_id) as session:
        actions = [r[0] for r in (await session.execute(text("select action from connector_activity"))).all()]
    assert actions.count("source_removed") == 2


async def test_deleting_a_knowledge_base_removes_its_sources_but_keeps_the_connection(
    client: httpx.AsyncClient, app: FastAPI, account: Account, fake_drive: FakeDriveClient
) -> None:
    kb_id, _ = await _source(client, account, fake_drive)
    deleted = await client.delete(f"/v1/knowledge-bases/{kb_id}", headers=account.headers)
    assert deleted.status_code == 200
    async with app.state.db.transaction(workspace_id=account.workspace_id) as session:
        left = (await session.execute(text("select count(*) from kb_sources"))).scalar_one()
        runs = (await session.execute(text("select count(*) from kb_sync_runs"))).scalar_one()
        conns = (await session.execute(text("select count(*) from connections"))).scalar_one()
    assert (left, runs, conns) == (0, 0, 1)
