"""Editing numbers (010 T037, FR-009, FR-011): the password is kept when omitted and removed on
request, termination and transport edits update the outbound trunk (or replace it), routing
failures change nothing, and agent changes leave active calls on their agent."""

from __future__ import annotations

import httpx

from tests.conftest import Account
from tests.fakes.livekit_fake import Channels
from tests.runtime_support import owner_sql


async def test_password_and_trunk_edits(
    client: httpx.AsyncClient, account: Account, channels: Channels
) -> None:
    number = await channels.number(client, account, auth_username="acme", auth_password="first-pass")
    path = f"/v1/phone-numbers/{number['id']}"
    (trunk_id,) = channels.sip.outbound

    kept = await client.patch(
        path, json={"termination_address": "sip:new.example.com:5070"}, headers=account.headers
    )
    assert kept.status_code == 200 and kept.json()["has_auth_password"] is True
    assert kept.json()["termination_address"] == "new.example.com:5070"
    trunk = channels.sip.outbound[trunk_id]
    assert trunk.address == "new.example.com:5070" and trunk.auth_password == "first-pass"

    switched = await client.patch(
        path, json={"transport": "tcp", "auth_password": "second"}, headers=account.headers
    )
    assert switched.status_code == 200 and switched.json()["transport"] == "tcp"
    assert channels.sip.outbound[trunk_id].transport == "tcp"
    assert channels.sip.outbound[trunk_id].auth_password == "second"

    removed = await client.patch(path, json={"remove_auth_password": True}, headers=account.headers)
    assert removed.json()["has_auth_password"] is False
    assert (
        channels.sip.outbound[trunk_id].auth_password is None
        or channels.sip.outbound[trunk_id].auth_password == ""
    )

    # The update API failing falls back to create-new-then-delete-old.
    channels.sip.fail_next.add("update_outbound_trunk")
    replaced = await client.patch(
        path, json={"termination_address": "third.example.com"}, headers=account.headers
    )
    assert replaced.status_code == 200
    (new_trunk,) = channels.sip.outbound
    assert new_trunk != trunk_id and channels.sip.outbound[new_trunk].address == "third.example.com"

    # Both failing: 502 and nothing changed.
    channels.sip.fail_next.update({"update_outbound_trunk", "create_outbound_trunk"})
    failed = await client.patch(
        path, json={"termination_address": "fourth.example.com"}, headers=account.headers
    )
    assert failed.status_code == 502 and failed.json()["code"] == "routing_update_failed"
    current = (await client.get(path, headers=account.headers)).json()
    assert current["termination_address"] == "third.example.com"


async def test_cidr_edit_updates_inbound_trunk_and_keeps_the_rule(
    client: httpx.AsyncClient, account: Account, channels: Channels
) -> None:
    agent = channels.agent(account.workspace_id)
    number = await channels.number(client, account, inbound_agent_id=agent)
    path = f"/v1/phone-numbers/{number['id']}"
    channels.sip.fail_next.add("update_inbound_trunk")  # forces a replacement inbound trunk
    response = await client.patch(
        path, json={"inbound_allowed_cidrs": ["198.51.100.0/24"]}, headers=account.headers
    )
    assert response.status_code == 200 and response.json()["inbound_allowed_cidrs"] == ["198.51.100.0/24"]
    (trunk_id,) = channels.sip.inbound
    (rule,) = channels.sip.rules.values()
    assert list(rule.trunk_ids) == [trunk_id]  # the rule follows the new trunk


async def test_agent_change_keeps_active_calls(
    client: httpx.AsyncClient, account: Account, channels: Channels
) -> None:
    first = channels.agent(account.workspace_id)
    second = channels.agent(account.workspace_id)
    number = await channels.number(client, account, inbound_agent_id=first)
    claim = await channels.claim_inbound(
        client, channel="sip_inbound", route_ref=number["id"], trunk_number=number["e164"]
    )
    rules_before = dict(channels.sip.rules)
    changed = await client.patch(
        f"/v1/phone-numbers/{number['id']}", json={"inbound_agent_id": second}, headers=account.headers
    )
    assert changed.status_code == 200 and channels.sip.rules == rules_before
    assert owner_sql("select agent_id, status from calls where id = %s", (claim["call_id"],)) == [
        (first, "queued")
    ]
    later = await channels.claim_inbound(
        client, channel="sip_inbound", route_ref=number["id"], trunk_number=number["e164"]
    )
    assert later["runtime"]["agent_id"] == second
    bad = await client.patch(f"/v1/phone-numbers/{number['id']}", json={}, headers=account.headers)
    assert bad.status_code == 422
