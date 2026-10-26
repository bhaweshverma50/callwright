"""WhatsApp channel setup against the real Graph client with respx (010 T047, T083, R10):
rejected token saves nothing; mismatch names both numbers; success is ``setup_incomplete`` with
Meta's SIP credentials on the trunk; trunk failure is ``error`` with compensation; retry
recovers; duplicates are refused; WhatsApp unreachable is a 502 that saves nothing."""

from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
import pytest_asyncio
import respx
from fastapi import FastAPI

from app.whatsapp.graph_client import LiveWhatsAppGraph
from tests.conftest import Account
from tests.fakes.livekit_fake import Channels, whatsapp_body
from tests.runtime_support import owner_sql

GRAPH = "https://graph.facebook.com/v23.0"


@pytest_asyncio.fixture
async def live_graph(app: FastAPI, channels: Channels) -> AsyncIterator[respx.MockRouter]:
    graph = LiveWhatsAppGraph(app.state.settings)
    app.state.whatsapp_graph = graph
    with respx.mock(assert_all_called=False) as router:
        yield router
    await graph.aclose()


def meta_ok(router: respx.MockRouter, meta_id: str, display: str, password: str = "meta-sip-pass") -> None:
    router.get(f"{GRAPH}/{meta_id}").respond(
        200, json={"display_phone_number": display, "verified_name": "Acme"}
    )
    router.post(f"{GRAPH}/{meta_id}/settings").respond(200, json={"success": True})
    router.get(f"{GRAPH}/{meta_id}/settings").respond(
        200,
        json={
            "calling": {
                "status": "ENABLED",
                "sip": {"status": "ENABLED", "servers": [{"hostname": "x", "sip_user_password": password}]},
            }
        },
    )


def _channels(workspace_id: str) -> int:
    return int(
        owner_sql("select count(*) from whatsapp_channels where workspace_id = %s", (workspace_id,))[0][0]
    )


async def test_rejected_token_saves_nothing(
    client: httpx.AsyncClient, account: Account, channels: Channels, live_graph: respx.MockRouter
) -> None:
    body = whatsapp_body()
    live_graph.get(f"{GRAPH}/{body['meta_phone_number_id']}").respond(
        401, json={"error": {"message": "Error validating access token: Session has expired", "code": 190}}
    )
    response = await client.post("/v1/whatsapp/channels", json=body, headers=account.headers)
    assert response.status_code == 422 and response.json()["code"] == "whatsapp_token_rejected"
    assert "Session has expired" in response.json()["detail"]
    assert _channels(account.workspace_id) == 0 and channels.sip.inbound == {}


async def test_number_mismatch_names_both(
    client: httpx.AsyncClient, account: Account, channels: Channels, live_graph: respx.MockRouter
) -> None:
    body = whatsapp_body()
    meta_ok(live_graph, body["meta_phone_number_id"], "+1 650-555-0100")
    response = await client.post("/v1/whatsapp/channels", json=body, headers=account.headers)
    assert response.status_code == 422 and response.json()["code"] == "whatsapp_number_mismatch"
    assert "+1 650-555-0100" in response.json()["detail"] and body["e164"] in response.json()["detail"]
    assert _channels(account.workspace_id) == 0


async def test_success_trunk_failure_and_retry(
    client: httpx.AsyncClient, account: Account, channels: Channels, live_graph: respx.MockRouter
) -> None:
    agent = channels.agent(account.workspace_id)
    body = whatsapp_body(inbound_agent_id=agent)
    digits = body["e164"][1:]
    meta_ok(
        live_graph, body["meta_phone_number_id"], f"+{digits[0]} {digits[1:4]}-{digits[4:7]}-{digits[7:]}"
    )
    channels.sip.fail_next.add("create_dispatch_rule")
    created = await client.post("/v1/whatsapp/channels", json=body, headers=account.headers)
    assert created.status_code == 201
    channel = created.json()
    assert channel["status"] == "error" and "simulated" in channel["status_detail"]
    assert channel["credentials_verified_at"] and channel["calling_enabled_at"]
    assert channels.sip.inbound == {} and channels.sip.rules == {}  # compensated
    settings_call = next(c for c in live_graph.calls if c.request.method == "POST")
    assert b'"status":"ENABLED"' in settings_call.request.content.replace(b" ", b"")

    retried = await client.post(f"/v1/whatsapp/channels/{channel['id']}/retry-setup", headers=account.headers)
    assert retried.status_code == 200 and retried.json()["status"] == "setup_incomplete"
    (trunk,) = channels.sip.inbound.values()
    assert trunk.auth_username == digits and trunk.auth_password == "meta-sip-pass"
    assert trunk.require_media_encryption is True and list(trunk.numbers) == [body["e164"]]
    (rule,) = channels.sip.rules.values()
    assert rule.agent_metadata == {"channel": "whatsapp", "route_ref": channel["id"]}

    duplicate = await client.post("/v1/whatsapp/channels", json=body, headers=account.headers)
    assert duplicate.status_code == 409 and duplicate.json()["code"] == "whatsapp_number_already_connected"
    reused_token = await client.post(
        "/v1/whatsapp/channels",
        json=whatsapp_body(verify_token=body["verify_token"]),
        headers=account.headers,
    )
    assert reused_token.status_code == 409 and reused_token.json()["code"] == "verify_token_in_use"


async def test_unreachable_saves_nothing_and_bad_id_is_422(
    client: httpx.AsyncClient, account: Account, channels: Channels, live_graph: respx.MockRouter
) -> None:
    body = whatsapp_body()
    live_graph.get(f"{GRAPH}/{body['meta_phone_number_id']}").mock(
        side_effect=httpx.ConnectTimeout("timed out")
    )
    response = await client.post("/v1/whatsapp/channels", json=body, headers=account.headers)
    assert response.status_code == 502 and response.json()["code"] == "whatsapp_unreachable"
    live_graph.get(f"{GRAPH}/{body['meta_phone_number_id']}").respond(503)
    response = await client.post("/v1/whatsapp/channels", json=body, headers=account.headers)
    assert response.status_code == 502
    assert _channels(account.workspace_id) == 0
    bad = await client.post(
        "/v1/whatsapp/channels", json={**body, "meta_phone_number_id": "12ab5"}, headers=account.headers
    )
    assert bad.status_code == 422 and bad.json()["errors"][0]["pointer"] == "/meta_phone_number_id"


async def test_expired_token_on_retry_marks_error(
    client: httpx.AsyncClient, account: Account, channels: Channels, live_graph: respx.MockRouter
) -> None:
    body = whatsapp_body()
    meta_ok(live_graph, body["meta_phone_number_id"], body["e164"])
    channel = (await client.post("/v1/whatsapp/channels", json=body, headers=account.headers)).json()
    live_graph.get(f"{GRAPH}/{body['meta_phone_number_id']}").respond(
        400, json={"error": {"message": "Access token has expired", "code": 190}}
    )
    retried = await client.post(f"/v1/whatsapp/channels/{channel['id']}/retry-setup", headers=account.headers)
    assert retried.status_code == 200 and retried.json()["status"] == "error"
    assert "Access token has expired" in retried.json()["status_detail"]
