"""First sync of a Drive folder into a knowledge base (022 US2, T035)."""

from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import text

from app.knowledge import service
from app.knowledge.sources.fake_content import make_pdf
from app.knowledge.sources.fake_drive import FakeDriveClient
from tests.conftest import Account
from tests.connector_helpers import (
    add_source,
    connect,
    documents,
    fake_drive,
    make_kb,
    settle,
    synced_source,
)
from tests.contract.test_knowledge_contract import fake_embedder

__all__ = ["fake_drive", "fake_embedder"]


async def test_clinic_folder_imports_supported_files_and_lists_the_rest(
    client: httpx.AsyncClient, app: FastAPI, account: Account, fake_drive: FakeDriveClient
) -> None:
    root = fake_drive.seed("clinic")["Clinic policies"]
    conn = await connect(client, account)
    kb_id = await make_kb(client, account)
    source = await synced_source(client, account, kb_id, conn["id"], root)
    assert source["root_name"] == "Clinic policies"
    assert source["state"] == "healthy" and source["document_count"] == 10
    assert source["last_run"]["trigger"] == "first" and source["last_run"]["status"] == "succeeded"
    assert source["last_run"]["counts"]["added"] == 10 and source["last_run"]["counts"]["skipped"] == 2
    issues = {i["name"]: i["reason"] for i in source["not_imported"]}
    assert issues == {"Slots": "unsupported_type", "Scanned archive.pdf": "too_large"}
    docs = await documents(client, account, kb_id)
    assert len(docs) == 10 and all(d["status"] == "ready" for d in docs)
    assert all(d["managed"] and d["source"]["source_id"] == source["id"] for d in docs)
    vaccination = next(d for d in docs if d["display_name"] == "Vaccination drive")
    assert vaccination["source"]["path"] == "2026"
    assert vaccination["source"]["web_view_link"].startswith("https://docs.google.com/document/d/")
    kb = (await client.get(f"/v1/knowledge-bases/{kb_id}", headers=account.headers)).json()
    assert kb["source_count"] == 1 and kb["attachable"] is True
    async with app.state.db.transaction(workspace_id=account.workspace_id) as session:
        actions = [r[0] for r in (await session.execute(text("select action from connector_activity"))).all()]
    assert "source_added" in actions


async def test_subfolders_can_be_left_out(
    client: httpx.AsyncClient, account: Account, fake_drive: FakeDriveClient
) -> None:
    root = fake_drive.seed("clinic")["Clinic policies"]
    conn = await connect(client, account)
    kb_id = await make_kb(client, account)
    source = await synced_source(client, account, kb_id, conn["id"], root, include_subfolders=False)
    assert source["document_count"] == 9
    assert "Vaccination drive" not in {d["display_name"] for d in await documents(client, account, kb_id)}


async def test_synced_documents_cannot_be_replaced_or_deleted_by_upload(
    client: httpx.AsyncClient, account: Account, fake_drive: FakeDriveClient
) -> None:
    root = fake_drive.seed("property")["Listings"]
    conn = await connect(client, account)
    kb_id = await make_kb(client, account)
    await synced_source(client, account, kb_id, conn["id"], root)
    doc = (await documents(client, account, kb_id))[0]
    deleted = await client.delete(
        f"/v1/knowledge-bases/{kb_id}/documents/{doc['id']}", headers=account.headers
    )
    assert deleted.status_code == 409 and deleted.json()["code"] == "managed_by_source"
    replaced = await client.post(
        f"/v1/knowledge-bases/{kb_id}/documents",
        files={"file": ("x.pdf", make_pdf([["A brand new replacement."]]), "application/pdf")},
        data={"replace_doc_id": doc["id"]},
        headers=account.headers,
    )
    assert replaced.status_code == 409 and replaced.json()["code"] == "managed_by_source"


async def test_identical_content_is_imported_once(
    client: httpx.AsyncClient, account: Account, fake_drive: FakeDriveClient
) -> None:
    lines = ["Visiting hours are 4 pm to 7 pm."]
    a = fake_drive.add_folder("A")
    b = fake_drive.add_folder("B")
    fake_drive.add_pdf(a, "Visiting.pdf", lines)
    fake_drive.add_pdf(b, "Visiting copy.pdf", lines)
    fake_drive.add_pdf(b, "Refunds.pdf", ["Refunds take five days."])
    conn = await connect(client, account)
    kb_id = await make_kb(client, account)
    uploaded = await client.post(
        f"/v1/knowledge-bases/{kb_id}/documents",
        files={"file": ("refunds.pdf", make_pdf([["Refunds take five days."]]), "application/pdf")},
        headers=account.headers,
    )
    assert uploaded.status_code == 202
    await settle()
    await synced_source(client, account, kb_id, conn["id"], a)
    second = await synced_source(client, account, kb_id, conn["id"], b)
    reasons = {i["name"]: (i["reason"], i["duplicate_of_doc_id"]) for i in second["not_imported"]}
    assert reasons["Visiting copy.pdf"][0] == "duplicate"
    assert reasons["Refunds.pdf"] == ("duplicate", uploaded.json()["id"])
    assert len(await documents(client, account, kb_id)) == 2


async def test_full_knowledge_base_imports_up_to_the_limit(
    client: httpx.AsyncClient, account: Account, fake_drive: FakeDriveClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(service, "MAX_DOCS_PER_KB", 5)
    root = fake_drive.seed("clinic")["Clinic policies"]
    conn = await connect(client, account)
    kb_id = await make_kb(client, account)
    source = await synced_source(client, account, kb_id, conn["id"], root)
    assert source["document_count"] == 5
    assert source["state"] == "needs_attention" and source["attention_reason"] == "kb_full"
    assert sum(1 for i in source["not_imported"] if i["reason"] == "kb_full") == 5


async def test_add_source_refusals(
    client: httpx.AsyncClient, account: Account, fake_drive: FakeDriveClient
) -> None:
    root = fake_drive.seed("property")["Listings"]
    conn = await connect(client, account)
    kb_id = await make_kb(client, account)
    first = await add_source(client, account, kb_id, conn["id"], root)
    assert first.status_code == 201
    await settle()
    again = await add_source(client, account, kb_id, conn["id"], root)
    assert again.status_code == 409 and again.json()["code"] == "source_exists"
    missing = await add_source(client, account, kb_id, conn["id"], "fld-does-not-exist")
    assert missing.status_code == 422
    fake_drive.revoked = True
    other_kb = await make_kb(client, account, "Second")
    revoked = await add_source(client, account, other_kb, conn["id"], root)
    assert revoked.status_code == 409 and revoked.json()["code"] == "connection_revoked"
