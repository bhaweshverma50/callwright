"""specs/013-guided-setup/contracts/preferences.yaml."""

from __future__ import annotations

import httpx

from tests.conftest import Account
from tests.contract.conftest import check


async def test_get_preferences_200_401(client: httpx.AsyncClient, account: Account) -> None:
    ok = check(await client.get("/v1/me/preferences", headers=account.headers))
    assert ok.status_code == 200
    assert ok.json() == {"onboarding": {"status": "not_started", "step": None, "updated_at": None}}
    assert check(await client.get("/v1/me/preferences")).status_code == 401


async def test_patch_preferences_200_401_422(client: httpx.AsyncClient, account: Account) -> None:
    body = {"onboarding": {"status": "in_progress", "step": "agents"}}
    ok = check(await client.patch("/v1/me/preferences", json=body, headers=account.headers))
    assert ok.status_code == 200
    assert ok.json()["onboarding"]["step"] == "agents"
    assert check(await client.patch("/v1/me/preferences", json=body)).status_code == 401
    bad = check(
        await client.patch(
            "/v1/me/preferences", json={"onboarding": {"status": "paused"}}, headers=account.headers
        )
    )
    assert bad.status_code == 422
