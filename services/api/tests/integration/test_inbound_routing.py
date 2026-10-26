"""Inbound claim routing for phone numbers (010 T014, research R4): admitted with from/to and
``phone_number_id``; a trunk number mismatch or a number that is not active is refused."""

from __future__ import annotations

import httpx

from tests.conftest import Account
from tests.fakes.livekit_fake import Channels
from tests.runtime_support import owner_sql


async def test_inbound_call_is_admitted_with_numbers(
    client: httpx.AsyncClient, account: Account, channels: Channels
) -> None:
    agent = channels.agent(account.workspace_id, call_behavior={"ring_duration_ms": 3000})
    number = await channels.number(client, account, inbound_agent_id=agent)
    claim = await channels.claim_inbound(
        client,
        channel="sip_inbound",
        route_ref=number["id"],
        trunk_number=number["e164"],
        caller="14085550123",
    )
    assert claim["admitted"], claim
    runtime = claim["runtime"]
    assert runtime["channel"] == "sip_inbound" and runtime["direction"] == "inbound"
    assert runtime["from_number"] == "+14085550123" and runtime["to_number"] == number["e164"]
    assert runtime["agent_id"] == agent
    assert runtime["config"]["call_behavior"]["ring_duration_ms"] == 3000
    row = owner_sql(
        "select channel, from_number, to_number, phone_number_id, status, route_detail "
        "from calls where id = %s",
        (claim["call_id"],),
    )
    assert row == [("sip_inbound", "+14085550123", number["e164"], number["id"], "queued", None)]
    listed = await client.get(f"/v1/phone-numbers/{number['id']}", headers=account.headers)
    assert listed.json()["active_call_count"] == 1


async def test_trunk_number_mismatch_is_refused(
    client: httpx.AsyncClient, account: Account, channels: Channels
) -> None:
    agent = channels.agent(account.workspace_id)
    number = await channels.number(client, account, inbound_agent_id=agent)
    claim = await channels.claim_inbound(
        client, channel="sip_inbound", route_ref=number["id"], trunk_number="+14155550000"
    )
    assert not claim["admitted"] and claim["refusal"]["diagnostic"] == "no_agent_for_caller"
    assert owner_sql("select count(*) from calls where phone_number_id = %s", (number["id"],)) == [(0,)]


async def test_number_that_is_not_active_is_refused(
    client: httpx.AsyncClient, account: Account, channels: Channels
) -> None:
    agent = channels.agent(account.workspace_id)
    number = await channels.number(client, account, inbound_agent_id=agent)
    for status in ("error", "draining"):
        owner_sql("update phone_numbers set status = %s where id = %s", (status, number["id"]))
        claim = await channels.claim_inbound(
            client, channel="sip_inbound", route_ref=number["id"], trunk_number=number["e164"]
        )
        assert not claim["admitted"]
    assert owner_sql("select count(*) from calls where phone_number_id = %s", (number["id"],)) == [(0,)]


async def test_unknown_route_ref_is_refused(client: httpx.AsyncClient, channels: Channels) -> None:
    claim = await channels.claim_inbound(
        client, channel="sip_inbound", route_ref="num_01ARZ3NDEKTSV4RRFFQ69G5FAV", trunk_number="+14155550100"
    )
    assert not claim["admitted"]
