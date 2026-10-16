"""contracts/workspaces.yaml (T029)."""

from __future__ import annotations

import httpx

from tests.conftest import Account
from tests.contract.conftest import check


async def test_me_200_401(client: httpx.AsyncClient, account: Account) -> None:
    assert check(await client.get("/v1/me", headers=account.headers)).status_code == 200
    assert check(await client.get("/v1/me")).status_code == 401


async def test_update_workspace_200_401_422(client: httpx.AsyncClient, account: Account) -> None:
    ok = check(await client.patch("/v1/workspaces/current", json={"name": "Ops"}, headers=account.headers))
    assert ok.status_code == 200
    toggled = check(
        await client.patch(
            "/v1/workspaces/current", json={"recording_default": False}, headers=account.headers
        )
    )
    assert toggled.json()["recording_default"] is False
    assert check(await client.patch("/v1/workspaces/current", json={"name": "x"})).status_code == 401
    bad = check(await client.patch("/v1/workspaces/current", json={"name": ""}, headers=account.headers))
    assert bad.status_code == 422
