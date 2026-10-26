"""contracts/whatsapp.yaml (010 T045): settings, channels, retry, caller routes, public webhook."""

from __future__ import annotations

import httpx

from app.whatsapp.signatures import sign
from tests.conftest import Account
from tests.contract.conftest import check
from tests.fakes.livekit_fake import Channels, whatsapp_body

MISSING = "/v1/whatsapp/channels/wa_01ARZ3NDEKTSV4RRFFQ69G5FAV"


async def test_settings_and_channel_crud(
    client: httpx.AsyncClient, account: Account, channels: Channels
) -> None:
    settings = check(await client.get("/v1/whatsapp/settings", headers=account.headers))
    assert settings.status_code == 200 and settings.json()["callback_url"].endswith("/v1/whatsapp/webhook")
    assert check(await client.get("/v1/whatsapp/settings")).status_code == 401

    body = whatsapp_body()
    created = check(await client.post("/v1/whatsapp/channels", json=body, headers=account.headers))
    assert created.status_code == 201
    channel = created.json()
    assert (
        channel["status"] == "setup_incomplete" and channel["access_token_last4"] == body["access_token"][-4:]
    )
    assert channel["has_app_secret"] is True and "access_token" not in channel
    assert check(await client.post("/v1/whatsapp/channels", json=body)).status_code == 401
    duplicate = check(await client.post("/v1/whatsapp/channels", json=body, headers=account.headers))
    assert duplicate.status_code == 409
    invalid = check(
        await client.post(
            "/v1/whatsapp/channels", json={**body, "meta_phone_number_id": "abc"}, headers=account.headers
        )
    )
    assert invalid.status_code == 422 and invalid.json()["errors"][0]["pointer"] == "/meta_phone_number_id"
    rejected = check(
        await client.post(
            "/v1/whatsapp/channels",
            json=whatsapp_body(access_token="invalid-token"),
            headers=account.headers,
        )
    )
    assert rejected.status_code == 422 and rejected.json()["code"] == "whatsapp_token_rejected"
    unreachable = check(
        await client.post(
            "/v1/whatsapp/channels", json=whatsapp_body(access_token="unreachable-x"), headers=account.headers
        )
    )
    assert unreachable.status_code == 502 and unreachable.json()["code"] == "whatsapp_unreachable"

    listed = check(await client.get("/v1/whatsapp/channels", headers=account.headers))
    assert listed.status_code == 200 and listed.json()["total"] == 1
    path = f"/v1/whatsapp/channels/{channel['id']}"
    assert check(await client.get(path, headers=account.headers)).status_code == 200
    assert check(await client.get(MISSING, headers=account.headers)).status_code == 404
    updated = check(await client.patch(path, json={"label": "Sales"}, headers=account.headers))
    assert updated.status_code == 200 and updated.json()["label"] == "Sales"
    assert check(await client.patch(MISSING, json={"label": "x"}, headers=account.headers)).status_code == 404
    retried = check(await client.post(f"{path}/retry-setup", headers=account.headers))
    assert retried.status_code == 200
    assert check(await client.post(f"{MISSING}/retry-setup", headers=account.headers)).status_code == 404
    assert check(await client.delete(path, headers=account.headers)).status_code == 204
    assert check(await client.delete(path, headers=account.headers)).status_code == 404


async def test_caller_routes(client: httpx.AsyncClient, account: Account, channels: Channels) -> None:
    channel = await channels.whatsapp(client, account)
    agent = channels.agent(account.workspace_id)
    base = f"/v1/whatsapp/channels/{channel['id']}/caller-routes"
    created = check(
        await client.post(
            base, json={"caller_number": "14085550123", "agent_id": agent}, headers=account.headers
        )
    )
    assert created.status_code == 201 and created.json()["caller_number"] == "+14085550123"
    route = created.json()
    dup = check(
        await client.post(
            base, json={"caller_number": "+14085550123", "agent_id": agent}, headers=account.headers
        )
    )
    assert dup.status_code == 409 and dup.json()["code"] == "duplicate_caller_route"
    listed = check(await client.get(f"{base}?caller=408", headers=account.headers))
    assert listed.status_code == 200 and listed.json()["items"][0]["agent_published"] is True
    other = channels.agent(account.workspace_id)
    changed = check(
        await client.patch(f"{base}/{route['id']}", json={"agent_id": other}, headers=account.headers)
    )
    assert changed.status_code == 200 and changed.json()["agent_id"] == other
    gone = f"{base}/wcr_01ARZ3NDEKTSV4RRFFQ69G5FAV"
    assert (
        check(await client.patch(gone, json={"agent_id": other}, headers=account.headers)).status_code == 404
    )
    assert check(await client.delete(f"{base}/{route['id']}", headers=account.headers)).status_code == 204
    assert check(await client.delete(f"{base}/{route['id']}", headers=account.headers)).status_code == 404
    assert check(await client.get(f"{MISSING}/caller-routes", headers=account.headers)).status_code == 404


async def test_public_webhook(client: httpx.AsyncClient, account: Account, channels: Channels) -> None:
    body = whatsapp_body()
    channel = await channels.whatsapp(client, account, **body)
    params = {
        "hub.mode": "subscribe",
        "hub.verify_token": body["verify_token"],
        "hub.challenge": "1158201444",
    }
    ok = check(await client.get("/v1/whatsapp/webhook", params=params))
    assert ok.status_code == 200 and ok.text == "1158201444"
    wrong = check(
        await client.get("/v1/whatsapp/webhook", params={**params, "hub.verify_token": "nope-nope"})
    )
    assert wrong.status_code == 403
    payload = (
        '{"object":"whatsapp_business_account","entry":[{"id":"1","changes":[{"field":"calls",'
        f'"value":{{"metadata":{{"phone_number_id":"{channel["meta_phone_number_id"]}"}}}}}}]}}]}}'
    ).encode()
    signed = check(
        await client.post(
            "/v1/whatsapp/webhook",
            content=payload,
            headers={
                "X-Hub-Signature-256": sign(body["app_secret"], payload),
                "Content-Type": "application/json",
            },
        )
    )
    assert signed.status_code == 200
    forged = check(
        await client.post(
            "/v1/whatsapp/webhook",
            content=payload,
            headers={"X-Hub-Signature-256": sign("wrong", payload), "Content-Type": "application/json"},
        )
    )
    assert forged.status_code == 401
