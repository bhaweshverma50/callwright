"""Contract tests for connections (022 T020) and, as they land, knowledge sources (T033, T082)."""

from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI

from app.knowledge.sources.fake_drive import FakeDriveClient
from tests.conftest import Account
from tests.connector_helpers import complete, fake_drive, start
from tests.contract.conftest import check

__all__ = ["fake_drive"]

MISSING_CONN = "conn_01ARZ3NDEKTSV4RRFFQ69G5FAV"


async def test_connection_operations_match_the_contract(
    client: httpx.AsyncClient, account: Account, fake_drive: FakeDriveClient
) -> None:
    check(await client.get("/v1/connections", headers=account.headers))
    started = check(await client.post("/v1/connections/google/start", json={}, headers=account.headers))
    assert started.status_code == 200
    params = await start(client, account)
    created = check(await complete(client, account, params))
    assert created.status_code == 201
    conn_id = created.json()["id"]
    again = check(await complete(client, account, await start(client, account)))
    assert again.status_code == 200
    check(await client.get(f"/v1/connections/{conn_id}", headers=account.headers))
    check(await client.post(f"/v1/connections/{conn_id}/test", headers=account.headers))
    bad = check(
        await client.post(
            "/v1/connections/google/complete", json={"state": "x" * 20, "code": "c"}, headers=account.headers
        )
    )
    assert bad.status_code == 400
    missing = check(await client.get(f"/v1/connections/{MISSING_CONN}", headers=account.headers))
    assert missing.status_code == 404
    check(await client.get("/v1/connections"))  # 401
    deleted = check(await client.delete(f"/v1/connections/{conn_id}", headers=account.headers))
    assert deleted.status_code == 204


async def test_unconfigured_server_matches_the_contract(
    client: httpx.AsyncClient, app: FastAPI, account: Account, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        app.state, "settings", app.state.settings.model_copy(update={"google_oauth_redirect_uri": ""})
    )
    response = check(await client.post("/v1/connections/google/start", json={}, headers=account.headers))
    assert response.status_code == 503


async def test_source_operations_match_the_contract(
    client: httpx.AsyncClient, account: Account, fake_drive: FakeDriveClient
) -> None:
    from tests.connector_helpers import connect, make_kb, settle
    from tests.contract.test_knowledge_contract import MISSING_DOC

    root = fake_drive.seed("clinic")["Clinic policies"]
    team = fake_drive.add_shared_drive("Team")
    fake_drive.add_folder("HR", parent=team)
    conn = await connect(client, account)
    h = account.headers
    check(await client.get(f"/v1/connections/{conn['id']}/drive/folders", headers=h))
    check(await client.get(f"/v1/connections/{conn['id']}/drive/folders?parent={root}", headers=h))
    check(await client.get(f"/v1/connections/{conn['id']}/drive/folders?drive_id={team}", headers=h))
    check(await client.get(f"/v1/connections/{conn['id']}/drive/shared-drives", headers=h))
    kb_id = await make_kb(client, account)
    base = f"/v1/knowledge-bases/{kb_id}/sources"
    created = check(
        await client.post(
            base, json={"connection_id": conn["id"], "root_kind": "folder", "root_id": root}, headers=h
        )
    )
    assert created.status_code == 201
    source_id = created.json()["id"]
    await settle()
    check(await client.get(base, headers=h))
    detail = check(await client.get(f"{base}/{source_id}", headers=h))
    assert detail.json()["not_imported"]
    docs = check(await client.get(f"/v1/knowledge-bases/{kb_id}/documents", headers=h)).json()["items"]
    assert docs[0]["source"]["source_id"] == source_id
    check(await client.get(f"/v1/knowledge-bases/{kb_id}/documents/{docs[0]['id']}", headers=h))
    managed = check(await client.delete(f"/v1/knowledge-bases/{kb_id}/documents/{docs[0]['id']}", headers=h))
    assert managed.status_code == 409
    check(await client.patch(f"{base}/{source_id}", json={"interval_minutes": 60}, headers=h))
    bad = check(await client.patch(f"{base}/{source_id}", json={"interval_minutes": 2}, headers=h))
    assert bad.status_code == 422
    queued = check(await client.post(f"{base}/{source_id}/sync", headers=h))
    assert queued.status_code == 202
    await settle()
    runs = check(await client.get(f"{base}/{source_id}/runs", headers=h)).json()["items"]
    check(await client.get(f"{base}/{source_id}/runs/{runs[0]['id']}", headers=h))
    nothing = check(await client.post(f"{base}/{source_id}/held-archive/confirm", headers=h))
    assert nothing.status_code == 409
    not_archived = check(
        await client.post(f"/v1/knowledge-bases/{kb_id}/documents/{docs[0]['id']}/restore", headers=h)
    )
    assert not_archived.status_code == 409
    not_kept = check(
        await client.post(f"/v1/knowledge-bases/{kb_id}/documents/{docs[0]['id']}/archive", headers=h)
    )
    assert not_kept.status_code == 409
    missing = check(
        await client.post(f"/v1/knowledge-bases/{kb_id}/documents/{MISSING_DOC}/restore", headers=h)
    )
    assert missing.status_code == 404
    taken = check(
        await client.post(
            base, json={"connection_id": conn["id"], "root_kind": "folder", "root_id": root}, headers=h
        )
    )
    assert taken.status_code == 409
    removed = check(await client.delete(f"{base}/{source_id}?documents=archive", headers=h))
    assert removed.status_code == 204
    archived = check(await client.get(f"/v1/knowledge-bases/{kb_id}/documents?status=archived", headers=h))
    assert archived.json()["total"] == 10
    restored = check(
        await client.post(f"/v1/knowledge-bases/{kb_id}/documents/{docs[0]['id']}/restore", headers=h)
    )
    assert restored.status_code == 200 and restored.json()["status"] == "ready"
