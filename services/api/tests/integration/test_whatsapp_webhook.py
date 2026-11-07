"""Public WhatsApp webhook (010 T048, FR-023, FR-024): the challenge is echoed and the channel
becomes ``active``; a wrong token is 403; a bad signature is 401; an unknown number id is 200 and
ignored; answers come well under 5 s."""

from __future__ import annotations

import json
import time

import httpx

from app.channels.whatsapp.signatures import sign
from tests.conftest import Account
from tests.fakes.livekit_fake import Channels, whatsapp_body


def _payload(meta_id: str) -> bytes:
    return json.dumps(
        {
            "object": "whatsapp_business_account",
            "entry": [
                {
                    "id": "1",
                    "changes": [{"field": "calls", "value": {"metadata": {"phone_number_id": meta_id}}}],
                }
            ],
        }
    ).encode()


async def test_verification_and_notifications(
    client: httpx.AsyncClient, account: Account, channels: Channels
) -> None:
    body = whatsapp_body()
    channel = await channels.whatsapp(client, account, **body)
    assert channel["webhook_verified_at"] is None
    started = time.monotonic()
    ok = await client.get(
        "/v1/whatsapp/webhook",
        params={"hub.mode": "subscribe", "hub.verify_token": body["verify_token"], "hub.challenge": "abc123"},
    )
    assert (
        ok.status_code == 200 and ok.text == "abc123" and ok.headers["content-type"].startswith("text/plain")
    )
    current = (await client.get(f"/v1/whatsapp/channels/{channel['id']}", headers=account.headers)).json()
    assert current["status"] == "active" and current["webhook_verified_at"]

    bad_mode = await client.get(
        "/v1/whatsapp/webhook",
        params={"hub.mode": "unsubscribe", "hub.verify_token": body["verify_token"], "hub.challenge": "x"},
    )
    assert bad_mode.status_code == 403

    payload = _payload(channel["meta_phone_number_id"])
    accepted = await client.post(
        "/v1/whatsapp/webhook",
        content=payload,
        headers={"X-Hub-Signature-256": sign(body["app_secret"], payload)},
    )
    assert accepted.status_code == 200
    seen = (await client.get(f"/v1/whatsapp/channels/{channel['id']}", headers=account.headers)).json()
    assert seen["last_webhook_at"]
    tampered = await client.post(
        "/v1/whatsapp/webhook",
        content=payload + b" ",
        headers={"X-Hub-Signature-256": sign(body["app_secret"], payload)},
    )
    assert tampered.status_code == 401
    unknown = _payload("999999999999")
    ignored = await client.post(
        "/v1/whatsapp/webhook", content=unknown, headers={"X-Hub-Signature-256": sign("x", unknown)}
    )
    assert ignored.status_code == 200
    assert time.monotonic() - started < 5


async def test_new_verify_token_needs_verification_again(
    client: httpx.AsyncClient, account: Account, channels: Channels
) -> None:
    body = whatsapp_body()
    channel = await channels.whatsapp(client, account, **body)
    await client.get(
        "/v1/whatsapp/webhook",
        params={"hub.mode": "subscribe", "hub.verify_token": body["verify_token"], "hub.challenge": "1"},
    )
    changed = await client.patch(
        f"/v1/whatsapp/channels/{channel['id']}",
        json={"verify_token": "brand-new-token-1"},
        headers=account.headers,
    )
    assert changed.status_code == 200 and changed.json()["status"] == "setup_incomplete"
    assert changed.json()["verify_token_last4"] == "en-1"
    old = await client.get(
        "/v1/whatsapp/webhook",
        params={"hub.mode": "subscribe", "hub.verify_token": body["verify_token"], "hub.challenge": "1"},
    )
    assert old.status_code == 403
