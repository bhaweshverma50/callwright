"""Money test (010 T012): a number without an inbound agent has no dispatch rule and its calls
create no call row or charge; an agent unpublished at routing time gives ``admitted: false`` and
a ``failed`` call that is never billed."""

from __future__ import annotations

import httpx

from tests.conftest import Account
from tests.fakes.livekit_fake import Channels
from tests.runtime_support import owner_sql


async def test_no_agent_means_no_rule_no_call_no_charge(
    client: httpx.AsyncClient, account: Account, channels: Channels
) -> None:
    agent = channels.agent(account.workspace_id)
    number = await channels.number(client, account, inbound_agent_id=agent)
    assert len(channels.sip.rules) == 1
    detached = await client.patch(
        f"/v1/phone-numbers/{number['id']}", json={"inbound_agent_id": None}, headers=account.headers
    )
    assert detached.status_code == 200 and detached.json()["inbound_agent_id"] is None
    assert channels.sip.rules == {}  # the SIP edge now declines the call
    assert owner_sql("select lk_dispatch_rule_id from phone_numbers where id = %s", (number["id"],)) == [
        (None,)
    ]
    # Even a stray dispatch is refused before any call row exists.
    claim = await channels.claim_inbound(
        client, channel="sip_inbound", route_ref=number["id"], trunk_number=number["e164"]
    )
    assert not claim["admitted"]
    assert owner_sql("select count(*) from calls where phone_number_id = %s", (number["id"],)) == [(0,)]
    assert owner_sql(
        "select count(*) from credit_transactions where workspace_id = %s and type = 'call_charge'",
        (account.workspace_id,),
    ) == [(0,)]


async def test_unpublished_agent_at_routing_time_fails_without_charge(
    client: httpx.AsyncClient, account: Account, channels: Channels
) -> None:
    agent = channels.agent(account.workspace_id)
    number = await channels.number(client, account, inbound_agent_id=agent)
    channels.runtime.versions.agents[agent].published = None  # unpublished after attachment
    claim = await channels.claim_inbound(
        client, channel="sip_inbound", route_ref=number["id"], trunk_number=number["e164"]
    )
    assert not claim["admitted"] and claim["refusal"]["diagnostic"] == "agent_not_published"
    row = owner_sql(
        "select status, billable_seconds, phone_number_id from calls where id = %s", (claim["call_id"],)
    )
    assert row == [("failed", 0, number["id"])]
    await channels.runtime.run_jobs()
    assert owner_sql("select count(*) from call_costs where call_id = %s", (claim["call_id"],)) == [(0,)]
    assert owner_sql(
        "select count(*) from credit_transactions where workspace_id = %s and type = 'call_charge'",
        (account.workspace_id,),
    ) == [(0,)]
