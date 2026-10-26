"""WhatsApp claim routing (010 T049, FR-027): the default agent is admitted with channel
``whatsapp`` and the normalised caller number; with no agent the call is declined, no charge."""

from __future__ import annotations

import httpx

from tests.conftest import Account
from tests.fakes.livekit_fake import Channels
from tests.runtime_support import owner_sql


async def test_default_agent_and_decline(
    client: httpx.AsyncClient, account: Account, channels: Channels
) -> None:
    agent = channels.agent(account.workspace_id)
    channel = await channels.whatsapp(client, account, inbound_agent_id=agent)
    claim = await channels.claim_inbound(
        client,
        channel="whatsapp",
        route_ref=channel["id"],
        trunk_number=channel["e164"],
        caller="919876543210",
    )
    assert claim["admitted"], claim
    assert claim["runtime"]["channel"] == "whatsapp" and claim["runtime"]["from_number"] == "+919876543210"
    assert owner_sql(
        "select channel, whatsapp_channel_id, from_number from calls where id = %s", (claim["call_id"],)
    ) == [("whatsapp", channel["id"], "+919876543210")]

    detached = await client.patch(
        f"/v1/whatsapp/channels/{channel['id']}", json={"inbound_agent_id": None}, headers=account.headers
    )
    assert detached.status_code == 200 and channels.sip.rules == {}
    declined = await channels.claim_inbound(
        client, channel="whatsapp", route_ref=channel["id"], trunk_number=channel["e164"]
    )
    assert not declined["admitted"]
    assert owner_sql("select count(*) from calls where whatsapp_channel_id = %s", (channel["id"],)) == [(1,)]
    assert owner_sql(
        "select count(*) from credit_transactions where workspace_id = %s and type = 'call_charge'",
        (account.workspace_id,),
    ) == [(0,)]


async def test_same_number_as_phone_and_whatsapp(
    client: httpx.AsyncClient, account: Account, channels: Channels
) -> None:
    agent = channels.agent(account.workspace_id)
    number = await channels.number(client, account, inbound_agent_id=agent)
    channel = await channels.whatsapp(client, account, e164=number["e164"], inbound_agent_id=agent)
    phone = await channels.claim_inbound(
        client, channel="sip_inbound", route_ref=number["id"], trunk_number=number["e164"]
    )
    wa = await channels.claim_inbound(
        client, channel="whatsapp", route_ref=channel["id"], trunk_number=channel["e164"]
    )
    assert phone["runtime"]["channel"] == "sip_inbound" and wa["runtime"]["channel"] == "whatsapp"
