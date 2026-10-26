"""contracts/phone_numbers.yaml (010 T011): list, import, sip-settings, get, patch agents, retry."""

from __future__ import annotations

import httpx

from tests.conftest import Account
from tests.contract.conftest import check
from tests.fakes.livekit_fake import Channels, fresh_e164

MISSING = "/v1/phone-numbers/num_01ARZ3NDEKTSV4RRFFQ69G5FAV"


async def test_import_list_get_201_200_401_404_422(
    client: httpx.AsyncClient, account: Account, channels: Channels
) -> None:
    body = {
        "e164": fresh_e164(),
        "label": "Main Office Line",
        "termination_address": "sip:trunk.example.com:5060",
    }
    created = check(await client.post("/v1/phone-numbers", json=body, headers=account.headers))
    assert created.status_code == 201
    number = created.json()
    assert number["status"] == "active" and number["termination_address"] == "trunk.example.com:5060"
    assert number["has_auth_password"] is False and number["active_call_count"] == 0
    assert check(await client.post("/v1/phone-numbers", json=body)).status_code == 401
    bad = check(
        await client.post("/v1/phone-numbers", json={**body, "e164": "4155550100"}, headers=account.headers)
    )
    assert bad.status_code == 422 and bad.json()["errors"][0]["pointer"] == "/e164"

    listed = check(await client.get("/v1/phone-numbers", headers=account.headers))
    assert listed.status_code == 200 and [n["id"] for n in listed.json()["items"]] == [number["id"]]
    assert (
        check(await client.get("/v1/phone-numbers?status=active", headers=account.headers)).json()["total"]
        == 1
    )
    assert check(await client.get("/v1/phone-numbers")).status_code == 401

    got = check(await client.get(f"/v1/phone-numbers/{number['id']}", headers=account.headers))
    assert got.status_code == 200 and got.json()["direct_uri"].startswith(f"sip:{body['e164']}@")
    assert check(await client.get(MISSING, headers=account.headers)).status_code == 404
    assert check(await client.get(f"/v1/phone-numbers/{number['id']}")).status_code == 401


async def test_sip_settings(client: httpx.AsyncClient, account: Account, channels: Channels) -> None:
    response = check(await client.get("/v1/phone-numbers/sip-settings", headers=account.headers))
    assert response.status_code == 200
    body = response.json()
    assert body["origination_uri"].startswith("sip:") and "{e164}" in body["direct_uri_template"]
    assert body["telephony_enabled"] is False  # tests run with the in-memory SIP service
    assert check(await client.get("/v1/phone-numbers/sip-settings")).status_code == 401


async def test_patch_agents_and_retry(
    client: httpx.AsyncClient, account: Account, channels: Channels
) -> None:
    number = await channels.number(client, account)
    agent = channels.agent(account.workspace_id)
    path = f"/v1/phone-numbers/{number['id']}"
    attached = check(await client.patch(path, json={"inbound_agent_id": agent}, headers=account.headers))
    assert attached.status_code == 200 and attached.json()["inbound_agent_id"] == agent
    unpublished = channels.agent(account.workspace_id, published=False)
    refused = check(
        await client.patch(path, json={"outbound_agent_id": unpublished}, headers=account.headers)
    )
    assert refused.status_code == 422 and refused.json()["errors"][0]["code"] == "agent_not_published"
    assert check(await client.patch(MISSING, json={"label": "x"}, headers=account.headers)).status_code == 404
    assert check(await client.patch(path, json={"label": "x"})).status_code == 401

    not_error = check(await client.post(f"{path}/retry-provisioning", headers=account.headers))
    assert not_error.status_code == 409
    assert (
        check(await client.post(f"{MISSING}/retry-provisioning", headers=account.headers)).status_code == 404
    )
    assert check(await client.post(f"{path}/retry-provisioning")).status_code == 401


async def test_delete_204_202_409(client: httpx.AsyncClient, account: Account, channels: Channels) -> None:
    number = await channels.number(client, account)
    gone = check(await client.delete(f"/v1/phone-numbers/{number['id']}", headers=account.headers))
    assert gone.status_code == 204
    assert (
        check(await client.get(f"/v1/phone-numbers/{number['id']}", headers=account.headers)).status_code
        == 404
    )
    assert check(await client.delete(MISSING, headers=account.headers)).status_code == 404
