"""Settings save (T094, FR-017, US1.5)."""

from __future__ import annotations

import httpx

from tests.conftest import Account


async def test_name_and_recording_default_update_independently(
    client: httpx.AsyncClient, account: Account
) -> None:
    renamed = await client.patch("/v1/workspaces/current", json={"name": "Ops"}, headers=account.headers)
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "Ops"
    assert renamed.json()["recording_default"] is True
    toggled = await client.patch(
        "/v1/workspaces/current", json={"recording_default": False}, headers=account.headers
    )
    assert toggled.status_code == 200
    assert toggled.json()["name"] == "Ops"
    me = (await client.get("/v1/me", headers=account.headers)).json()
    assert me["workspace"]["recording_default"] is False
    assert me["workspace"]["concurrency_limit"] == 5
    assert me["workspace"]["name"] == "Ops"


async def test_empty_name_rejected_and_nothing_saved(client: httpx.AsyncClient, account: Account) -> None:
    before = (await client.get("/v1/me", headers=account.headers)).json()["workspace"]
    for body in ({"name": ""}, {"name": "   "}, {"name": "x" * 81}, {"name": "ok", "concurrency_limit": 50}, {}):
        response = await client.patch("/v1/workspaces/current", json=body, headers=account.headers)
        assert response.status_code == 422, body
        assert response.json()["errors"]
    after = (await client.get("/v1/me", headers=account.headers)).json()["workspace"]
    assert after == before


async def test_name_error_points_at_the_field(client: httpx.AsyncClient, account: Account) -> None:
    response = await client.patch("/v1/workspaces/current", json={"name": ""}, headers=account.headers)
    assert response.json()["errors"][0]["pointer"] == "/name"
