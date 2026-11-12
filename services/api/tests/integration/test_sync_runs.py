"""Sync history (022 US5, T083): runs newest first with triggers, capped errors, 90-day purge,
and connection activity."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
from fastapi import FastAPI
from sqlalchemy import text

from app.knowledge.sources import jobs as sync_jobs
from app.knowledge.sources import sync
from app.knowledge.sources.fake_drive import SHEET, FakeDriveClient
from tests.conftest import Account
from tests.connector_helpers import connect, fake_drive, make_kb, run_of, sync_now, synced_source
from tests.contract.test_knowledge_contract import fake_embedder

__all__ = ["fake_drive", "fake_embedder"]


async def test_runs_list_detail_and_purge(
    client: httpx.AsyncClient, app: FastAPI, account: Account, fake_drive: FakeDriveClient
) -> None:
    root = fake_drive.seed("clinic")["Clinic policies"]
    conn = await connect(client, account)
    kb_id = await make_kb(client, account)
    source = await synced_source(client, account, kb_id, conn["id"], root)
    await sync_now(app, source["id"], "manual")
    await sync_now(app, source["id"], "scheduled")
    base = f"/v1/knowledge-bases/{kb_id}/sources/{source['id']}/runs"
    runs = (await client.get(base, headers=account.headers)).json()
    assert [r["trigger"] for r in runs["items"]] == ["scheduled", "manual", "first"]
    first = await run_of(client, account, kb_id, source["id"], runs["items"][-1]["id"])
    assert {e["reason"] for e in first["errors"]} == {"unsupported_type", "too_large"}
    async with app.state.db.transaction(workspace_id=account.workspace_id) as session:
        await session.execute(
            text("update kb_sync_runs set started_at = :t where id = :id"),
            {"t": datetime.now(UTC) - timedelta(days=91), "id": first["id"]},
        )
    assert await sync_jobs.purge_runs(app.state.db) >= 1
    assert (await client.get(base, headers=account.headers)).json()["total"] == 2
    detail = (await client.get(f"/v1/connections/{conn['id']}", headers=account.headers)).json()
    assert {a["action"] for a in detail["activity"]} >= {"connection_added", "source_added"}


async def test_errors_are_capped(
    client: httpx.AsyncClient,
    app: FastAPI,
    account: Account,
    fake_drive: FakeDriveClient,
    monkeypatch: object,
) -> None:
    import pytest

    assert isinstance(monkeypatch, pytest.MonkeyPatch)
    monkeypatch.setattr(sync, "MAX_ERRORS", 3)
    root = fake_drive.add_folder("Sheets")
    for i in range(5):
        fake_drive.add_other(root, f"Sheet {i}", SHEET)
    conn = await connect(client, account)
    kb_id = await make_kb(client, account)
    source = await synced_source(client, account, kb_id, conn["id"], root)
    run = await run_of(client, account, kb_id, source["id"], source["last_run"]["id"])
    assert len(run["errors"]) == 3 and run["errors_truncated"] == 2 and run["counts"]["skipped"] == 5
