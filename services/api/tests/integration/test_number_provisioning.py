"""Import provisioning (010 T013, research R1, R2): active on success, error with compensation,
retry to active, global duplicates refused without workspace detail, ``sip:`` stripped."""

from __future__ import annotations

import httpx
from fastapi import FastAPI

from tests.conftest import Account, signup
from tests.fakes.livekit_fake import Channels, fresh_e164
from tests.runtime_support import owner_sql


async def test_import_creates_trunks_and_no_rule_without_agent(
    client: httpx.AsyncClient, account: Account, channels: Channels
) -> None:
    e164 = fresh_e164()
    number = await channels.number(
        client,
        account,
        e164=e164,
        termination_address="sips:trunk.example.com",
        auth_username="acme",
        auth_password="s3cret-pass",
        inbound_allowed_cidrs=["203.0.113.0/24"],
    )
    assert number["status"] == "active" and number["transport"] == "tls"
    assert number["termination_address"] == "trunk.example.com" and number["has_auth_password"]
    assert "auth_password" not in number
    assert len(channels.sip.inbound) == 1 and len(channels.sip.outbound) == 1 and not channels.sip.rules
    inbound = next(iter(channels.sip.inbound.values()))
    outbound = next(iter(channels.sip.outbound.values()))
    assert list(inbound.numbers) == [e164] and list(inbound.allowed_addresses) == ["203.0.113.0/24"]
    assert outbound.address == "trunk.example.com" and outbound.transport == "tls"
    assert outbound.auth_username == "acme" and outbound.auth_password == "s3cret-pass"


async def test_import_with_agent_creates_the_dispatch_rule(
    client: httpx.AsyncClient, account: Account, channels: Channels
) -> None:
    agent = channels.agent(account.workspace_id)
    number = await channels.number(client, account, inbound_agent_id=agent)
    (rule,) = channels.sip.rules.values()
    assert rule.agent_metadata == {"channel": "sip_inbound", "route_ref": number["id"]}
    assert rule.agent_name == "callwright-voice" and rule.room_prefix == "call-in-"


async def test_failure_compensates_and_retry_recovers(
    client: httpx.AsyncClient, account: Account, channels: Channels
) -> None:
    channels.sip.fail_next.add("create_outbound_trunk")
    number = await channels.number(client, account)
    assert number["status"] == "error" and "simulated" in number["status_detail"]
    assert not channels.sip.inbound and not channels.sip.outbound  # compensated
    assert owner_sql(
        "select lk_inbound_trunk_id, lk_outbound_trunk_id from phone_numbers where id = %s", (number["id"],)
    ) == [(None, None)]
    retried = await client.post(
        f"/v1/phone-numbers/{number['id']}/retry-provisioning", headers=account.headers
    )
    assert retried.status_code == 200 and retried.json()["status"] == "active"
    assert retried.json()["status_detail"] is None
    assert len(channels.sip.inbound) == 1 and len(channels.sip.outbound) == 1


async def test_duplicates_refused_across_workspaces(
    app: FastAPI, client: httpx.AsyncClient, account: Account, channels: Channels
) -> None:
    e164 = fresh_e164()
    await channels.number(client, account, e164=e164)
    other = await signup(client, app)
    body = {"e164": e164, "label": "Copy", "termination_address": "trunk.example.com"}
    response = await client.post("/v1/phone-numbers", json=body, headers=other.headers)
    assert response.status_code == 409 and response.json()["code"] == "number_already_registered"
    assert account.workspace_id not in response.text and account.email not in response.text
    same = await client.post("/v1/phone-numbers", json=body, headers=account.headers)
    assert same.status_code == 409


async def test_draining_number_blocks_reimport(
    client: httpx.AsyncClient, account: Account, channels: Channels
) -> None:
    e164 = fresh_e164()
    number = await channels.number(client, account, e164=e164)
    owner_sql("update phone_numbers set status = 'draining' where id = %s", (number["id"],))
    body = {"e164": e164, "label": "Again", "termination_address": "trunk.example.com"}
    response = await client.post("/v1/phone-numbers", json=body, headers=account.headers)
    assert response.status_code == 409 and response.json()["code"] == "number_being_deleted"


async def test_invalid_addresses_and_cidrs(
    client: httpx.AsyncClient, account: Account, channels: Channels
) -> None:
    base = {"e164": fresh_e164(), "label": "X"}
    for address in (
        "sip:+14155550100@trunk.example.com",
        "trunk.example.com/path",
        "trunk.example.com:70000",
    ):
        response = await client.post(
            "/v1/phone-numbers", json={**base, "termination_address": address}, headers=account.headers
        )
        assert response.status_code == 422, address
        assert response.json()["errors"][0]["pointer"] == "/termination_address"
    response = await client.post(
        "/v1/phone-numbers",
        json={**base, "termination_address": "trunk.example.com", "inbound_allowed_cidrs": ["10.0.0.1/8"]},
        headers=account.headers,
    )
    assert response.status_code == 422 and response.json()["errors"][0]["pointer"] == "/inbound_allowed_cidrs"
    empty = await client.post("/v1/phone-numbers", json={}, headers=account.headers)
    assert {e["pointer"] for e in empty.json()["errors"]} == {"/e164", "/label", "/termination_address"}
