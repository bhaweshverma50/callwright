"""A body cannot pick the workspace (010 T080): extra fields are refused and numbers land in the
token's workspace only."""

from __future__ import annotations

import httpx
from fastapi import FastAPI

from tests.conftest import Account, signup
from tests.fakes.livekit_fake import Channels, fresh_e164


async def test_extra_fields_are_refused(
    app: FastAPI, client: httpx.AsyncClient, account: Account, channels: Channels
) -> None:
    other = await signup(client, app)
    body = {"e164": fresh_e164(), "label": "X", "termination_address": "trunk.example-carrier.com"}
    for extra in ({"user_id": other.user_id}, {"workspace_id": other.workspace_id}):
        response = await client.post("/v1/phone-numbers", json={**body, **extra}, headers=account.headers)
        assert response.status_code == 422
        assert response.json()["errors"][0]["code"] == "unknown_field"
    created = await client.post("/v1/phone-numbers", json=body, headers=account.headers)
    assert created.status_code == 201
    mine = (await client.get("/v1/phone-numbers", headers=account.headers)).json()
    theirs = (await client.get("/v1/phone-numbers", headers=other.headers)).json()
    assert mine["total"] == 1 and theirs["total"] == 0
    assert (
        await client.get(f"/v1/phone-numbers/{created.json()['id']}", headers=other.headers)
    ).status_code == 404
