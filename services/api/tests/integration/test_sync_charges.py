"""Money tests for Drive sync (022 T037, T056): synced files are charged through 005's ingestion
charge once per document version, never twice, and unchanged files are never charged."""

from __future__ import annotations

import httpx
from fastapi import FastAPI
from sqlalchemy import text

from app.knowledge.sources.fake_drive import FakeDriveClient
from tests.conftest import Account
from tests.connector_helpers import connect, fake_drive, make_kb, settle, synced_source
from tests.contract.test_knowledge_contract import fake_embedder

__all__ = ["fake_drive", "fake_embedder"]


async def ingestion_charges(app: FastAPI, account: Account) -> list[str]:
    async with app.state.db.transaction(workspace_id=account.workspace_id) as session:
        rows = await session.execute(
            text(
                "select idempotency_key from usage_events where feature_key = 'knowledge_ingestion' "
                "order by idempotency_key"
            )
        )
        return [str(r[0]) for r in rows.all()]


async def test_first_sync_charges_once_per_document(
    client: httpx.AsyncClient, app: FastAPI, account: Account, fake_drive: FakeDriveClient
) -> None:
    root = fake_drive.seed("property")["Listings"]
    conn = await connect(client, account)
    kb_id = await make_kb(client, account)
    source = await synced_source(client, account, kb_id, conn["id"], root)
    charges = await ingestion_charges(app, account)
    assert len(charges) == 5 and len(set(charges)) == 5
    assert all(key.startswith("kb_ingest:doc_") for key in charges)

    from app.knowledge.sources import jobs as sync_jobs

    await sync_jobs.run_now(app.state, source["id"], "manual")
    await settle()
    assert await ingestion_charges(app, account) == charges


async def test_unchanged_200_file_source_charges_nothing_and_is_quick(
    client: httpx.AsyncClient, app: FastAPI, account: Account, fake_drive: FakeDriveClient
) -> None:
    import time

    from tests.connector_helpers import sync_now

    root = fake_drive.add_folder("Big")
    for n in range(200):
        fake_drive.add_doc(
            root, f"Note {n:03d}", [f"Procedure note {n} for the front desk team, version one."]
        )
    conn = await connect(client, account)
    kb_id = await make_kb(client, account)
    source = await synced_source(client, account, kb_id, conn["id"], root)
    assert source["document_count"] == 200
    charges = await ingestion_charges(app, account)
    downloads = fake_drive.calls
    started = time.monotonic()
    await sync_now(app, source["id"])
    assert time.monotonic() - started < 120  # SC-002
    assert fake_drive.calls - downloads == 3
    for n in (0, 1, 2):
        fake_drive.touch(next(i for i, x in fake_drive.nodes.items() if x.name == f"Note {n:03d}"))
    await sync_now(app, source["id"])
    assert await ingestion_charges(app, account) == charges
