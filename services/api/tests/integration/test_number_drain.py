"""Deletion with active calls (010 T036, FR-012, research R8): 409 with the count; ``when_idle``
drains (dispatch rule gone, outbound refused); the cron deletes once idle; past calls keep the
number and its label."""

from __future__ import annotations

import httpx
from fastapi import FastAPI

from app.phone_numbers.jobs import drain_channels_once
from tests.conftest import Account
from tests.fakes.livekit_fake import Channels, fresh_e164
from tests.runtime_support import owner_sql


async def test_delete_when_idle(
    app: FastAPI, client: httpx.AsyncClient, account: Account, channels: Channels
) -> None:
    agent = channels.agent(account.workspace_id)
    number = await channels.number(client, account, inbound_agent_id=agent, outbound_agent_id=agent)
    await channels.all_day(client, account)
    claim = await channels.claim_inbound(
        client, channel="sip_inbound", route_ref=number["id"], trunk_number=number["e164"]
    )
    assert claim["admitted"]
    path = f"/v1/phone-numbers/{number['id']}"

    refused = await client.delete(path, headers=account.headers)
    assert refused.status_code == 409 and refused.json()["code"] == "number_has_active_calls"
    assert refused.json()["active_call_count"] == 1

    draining = await client.delete(f"{path}?when_idle=true", headers=account.headers)
    assert draining.status_code == 202 and draining.json()["status"] == "draining"
    assert channels.sip.rules == {} and len(channels.sip.inbound) == 1  # trunks stay for now
    outbound = await channels.place(client, account, to_number=fresh_e164(), from_number=number["e164"])
    assert outbound.status_code == 409 and outbound.json()["code"] == "from_number_not_active"
    second = await channels.claim_inbound(
        client, channel="sip_inbound", route_ref=number["id"], trunk_number=number["e164"]
    )
    assert not second["admitted"]
    edit = await client.patch(path, json={"label": "x"}, headers=account.headers)
    assert edit.status_code == 409

    await drain_channels_once(app.state.db, channels.sip)  # still a call: nothing happens
    assert owner_sql("select status from phone_numbers where id = %s", (number["id"],)) == [("draining",)]
    owner_sql("update calls set status = 'ended', ended_at = now() where id = %s", (claim["call_id"],))
    assert await drain_channels_once(app.state.db, channels.sip) >= 1
    assert channels.sip.inbound == {} and channels.sip.outbound == {}
    assert (await client.get(path, headers=account.headers)).status_code == 404
    assert owner_sql(
        "select status, label, deleted_at is not null from phone_numbers where id = %s", (number["id"],)
    ) == [("deleted", "Main Office Line", True)]
    assert owner_sql("select phone_number_id from calls where id = %s", (claim["call_id"],)) == [
        (number["id"],)
    ]
    # The number can be imported again once deleted.
    again = await client.post(
        "/v1/phone-numbers",
        json={"e164": number["e164"], "label": "Back", "termination_address": "trunk.example.com"},
        headers=account.headers,
    )
    assert again.status_code == 201


async def test_delete_without_calls_is_immediate(
    client: httpx.AsyncClient, account: Account, channels: Channels
) -> None:
    agent = channels.agent(account.workspace_id)
    number = await channels.number(client, account, inbound_agent_id=agent, auth_password="pw-123456")
    assert (
        await client.delete(f"/v1/phone-numbers/{number['id']}", headers=account.headers)
    ).status_code == 204
    assert channels.sip.rules == {} and channels.sip.inbound == {} and channels.sip.outbound == {}
    assert owner_sql(
        "select count(*) from secrets where workspace_id = %s and name like 'phone_numbers/%%'",
        (account.workspace_id,),
    ) == [(0,)]


async def test_sip_failure_on_delete_leaves_number_draining_for_the_cron(
    app: FastAPI, client: httpx.AsyncClient, account: Account, channels: Channels
) -> None:
    number = await channels.number(client, account)
    channels.sip.fail_next.add("delete_trunk")
    response = await client.delete(f"/v1/phone-numbers/{number['id']}", headers=account.headers)
    assert response.status_code == 202 and response.json()["status"] == "draining"
    assert await drain_channels_once(app.state.db, channels.sip) >= 1
    assert channels.sip.inbound == {} and channels.sip.outbound == {}
