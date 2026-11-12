"""Connecting a Google account (022 US1, T022): create, decline, scope rules, reconnect, test,
revoke, remove, activity, and tokens never leaving the secrets store."""

from __future__ import annotations

import logging

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import text

from app.knowledge.sources.drive import SCOPE_DRIVE, SCOPE_SHEETS
from app.knowledge.sources.fake_drive import FAKE_EMAIL, FakeDriveClient
from tests.conftest import Account, signup
from tests.connector_helpers import complete, connect, fake_drive, start

__all__ = ["fake_drive"]

SECRET_MARKERS = ("fake-refresh-", "fake-access", "fake-code")


async def _activity(app: FastAPI, account: Account) -> list[str]:
    async with app.state.db.transaction(workspace_id=account.workspace_id) as session:
        rows = await session.execute(text("select action from connector_activity order by id"))
        return [r[0] for r in rows.all()]


async def test_connect_creates_a_healthy_connection(
    client: httpx.AsyncClient, app: FastAPI, account: Account, fake_drive: FakeDriveClient
) -> None:
    params = await start(client, account)
    response = await complete(client, account, params)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["account_email"] == FAKE_EMAIL
    assert body["health"] == "healthy" and body["sheets_access"] is True
    assert SCOPE_DRIVE in body["scopes"] and SCOPE_SHEETS in body["scopes"]
    assert not any(m in response.text for m in SECRET_MARKERS)
    listed = (await client.get("/v1/connections", headers=account.headers)).json()
    assert listed["google_configured"] is True
    assert [c["id"] for c in listed["items"]] == [body["id"]]
    assert await _activity(app, account) == ["connection_added"]


async def test_declined_consent_creates_nothing(
    client: httpx.AsyncClient, account: Account, fake_drive: FakeDriveClient
) -> None:
    fake_drive.consent_decline = True
    params = await start(client, account)
    assert params["error"] == "access_denied"
    response = await complete(client, account, params)
    assert response.status_code == 400 and response.json()["code"] == "oauth_declined"
    assert (await client.get("/v1/connections", headers=account.headers)).json()["items"] == []


async def test_drive_access_is_required_sheets_is_optional(
    client: httpx.AsyncClient, account: Account, fake_drive: FakeDriveClient
) -> None:
    fake_drive.granted_scopes = ("openid", "email", SCOPE_SHEETS)
    response = await complete(client, account, await start(client, account))
    assert response.status_code == 400 and response.json()["code"] == "oauth_scope_missing"
    fake_drive.granted_scopes = ("openid", "email", SCOPE_DRIVE)
    response = await complete(client, account, await start(client, account))
    assert response.status_code == 201
    assert response.json()["sheets_access"] is False


async def test_same_google_account_reconnects_the_existing_connection(
    client: httpx.AsyncClient, app: FastAPI, account: Account, fake_drive: FakeDriveClient
) -> None:
    first = await connect(client, account)
    response = await complete(client, account, await start(client, account))
    assert response.status_code == 200 and response.json()["id"] == first["id"]
    reconnect = await complete(client, account, await start(client, account, first["id"]))
    assert reconnect.status_code == 200
    assert await _activity(app, account) == [
        "connection_added",
        "connection_reconnected",
        "connection_reconnected",
    ]


async def test_reconnect_with_a_different_account_is_refused(
    client: httpx.AsyncClient, account: Account, fake_drive: FakeDriveClient
) -> None:
    first = await connect(client, account)
    params = await start(client, account, first["id"])
    response = await complete(client, account, params, code="account:other-subject:someone@example.com")
    assert response.status_code == 400
    problem = response.json()
    assert problem["code"] == "oauth_account_mismatch"
    assert "d***@example.com" in problem["detail"]
    after = (await client.get(f"/v1/connections/{first['id']}", headers=account.headers)).json()
    assert after["account_email"] == FAKE_EMAIL


async def test_state_from_another_workspace_is_refused(
    client: httpx.AsyncClient, app: FastAPI, account: Account, fake_drive: FakeDriveClient
) -> None:
    other = await signup(client, app)
    params = await start(client, account)
    response = await complete(client, other, params)
    assert response.status_code == 400 and response.json()["code"] == "oauth_state_invalid"
    again = await complete(client, account, params)
    assert again.status_code == 400  # consumed: single use


async def test_test_marks_a_revoked_connection(
    client: httpx.AsyncClient, account: Account, fake_drive: FakeDriveClient
) -> None:
    conn = await connect(client, account)
    ok = await client.post(f"/v1/connections/{conn['id']}/test", headers=account.headers)
    assert ok.status_code == 200 and ok.json()["health"] == "healthy" and ok.json()["last_checked_at"]
    fake_drive.revoked = True
    revoked = await client.post(f"/v1/connections/{conn['id']}/test", headers=account.headers)
    assert revoked.status_code == 200 and revoked.json()["health"] == "revoked"
    fake_drive.revoked = False
    healed = await complete(client, account, await start(client, account, conn["id"]))
    assert healed.status_code == 200 and healed.json()["health"] == "healthy"


async def test_remove_refused_while_in_use_then_revokes(
    client: httpx.AsyncClient, app: FastAPI, account: Account, fake_drive: FakeDriveClient
) -> None:
    conn = await connect(client, account)
    kb_id, source_id = "kb_01JX00000000000000000000AA", "ksrc_01JX00000000000000000000AA"
    async with app.state.db.transaction(workspace_id=account.workspace_id) as session:
        await session.execute(
            text("insert into knowledge_bases (id, workspace_id, name) values (:kb, :ws, 'Policies')"),
            {"kb": kb_id, "ws": account.workspace_id},
        )
        await session.execute(
            text(
                "insert into kb_sources (id, workspace_id, kb_id, connection_id, root_kind, root_id, "
                "root_name) values (:src, :ws, :kb, :c, 'folder', 'fld1', 'Policies')"
            ),
            {"src": source_id, "kb": kb_id, "ws": account.workspace_id, "c": conn["id"]},
        )
    refused = await client.delete(f"/v1/connections/{conn['id']}", headers=account.headers)
    assert refused.status_code == 409 and refused.json()["code"] == "connection_in_use"
    assert refused.json()["users"][0]["kb_name"] == "Policies"
    detail = (await client.get(f"/v1/connections/{conn['id']}", headers=account.headers)).json()
    assert detail["users"][0]["source_id"] == source_id
    async with app.state.db.transaction(workspace_id=account.workspace_id) as session:
        await session.execute(text("delete from kb_sources"))
    removed = await client.delete(f"/v1/connections/{conn['id']}", headers=account.headers)
    assert removed.status_code == 204
    assert fake_drive.revoked_tokens == ["fake-refresh-fake-google-subject-1"]
    async with app.state.db.transaction(workspace_id=account.workspace_id) as session:
        left = (
            await session.execute(text("select count(*) from secrets where name like 'conn:%'"))
        ).scalar_one()
    assert left == 0
    assert (await _activity(app, account))[-1] == "connection_removed"


async def test_tokens_never_reach_logs(
    client: httpx.AsyncClient, account: Account, fake_drive: FakeDriveClient, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    params = await start(client, account)
    conn = (await complete(client, account, params)).json()
    await client.post(f"/v1/connections/{conn['id']}/test", headers=account.headers)
    await client.get(f"/v1/connections/{conn['id']}", headers=account.headers)
    await client.delete(f"/v1/connections/{conn['id']}", headers=account.headers)
    logged = "\n".join(r.getMessage() for r in caplog.records)
    for marker in (*SECRET_MARKERS, params["state"]):
        assert marker not in logged


async def test_not_configured_returns_503(
    client: httpx.AsyncClient, app: FastAPI, account: Account, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        app.state, "settings", app.state.settings.model_copy(update={"google_oauth_client_id": ""})
    )
    listed = await client.get("/v1/connections", headers=account.headers)
    assert listed.status_code == 200 and listed.json()["google_configured"] is False
    response = await client.post("/v1/connections/google/start", json={}, headers=account.headers)
    assert response.status_code == 503 and response.json()["code"] == "connector_unavailable"
