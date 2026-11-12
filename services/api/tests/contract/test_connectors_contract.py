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
