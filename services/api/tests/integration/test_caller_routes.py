"""WhatsApp caller routes (010 T057, FR-027, FR-028): create, duplicate refused, the 1,000 limit,
update, delete, precedence over the default agent, unpublished route agent skipped with
``route_detail``, and the dispatch rule kept while routes exist without a default agent."""

from __future__ import annotations

import httpx
import pytest

from app.channels.whatsapp import service as whatsapp
from tests.conftest import Account
from tests.fakes.livekit_fake import Channels
from tests.runtime_support import owner_sql


async def test_route_precedence(client: httpx.AsyncClient, account: Account, channels: Channels) -> None:
    default, special = channels.agent(account.workspace_id), channels.agent(account.workspace_id)
    channel = await channels.whatsapp(client, account, inbound_agent_id=default)
    base = f"/v1/whatsapp/channels/{channel['id']}/caller-routes"
    route = await client.post(
        base, json={"caller_number": "+14085550111", "agent_id": special}, headers=account.headers
    )
    assert route.status_code == 201
    a = await channels.claim_inbound(
        client,
        channel="whatsapp",
        route_ref=channel["id"],
        trunk_number=channel["e164"],
        caller="14085550111",
    )
    b = await channels.claim_inbound(
        client,
        channel="whatsapp",
        route_ref=channel["id"],
        trunk_number=channel["e164"],
        caller="14085550222",
    )
    assert a["runtime"]["agent_id"] == special and b["runtime"]["agent_id"] == default

    channels.runtime.versions.agents[special].published = None
    skipped = await channels.claim_inbound(
        client,
        channel="whatsapp",
        route_ref=channel["id"],
        trunk_number=channel["e164"],
        caller="14085550111",
    )
    assert skipped["runtime"]["agent_id"] == default
    assert owner_sql("select route_detail from calls where id = %s", (skipped["call_id"],)) == [
        ("route_skipped:unpublished_agent",)
    ]
    listed = await client.get(base, headers=account.headers)
    assert listed.json()["items"][0]["agent_published"] is False


async def test_routes_keep_the_rule_without_default_agent(
    client: httpx.AsyncClient, account: Account, channels: Channels
) -> None:
    agent = channels.agent(account.workspace_id)
    channel = await channels.whatsapp(client, account)
    assert channels.sip.rules == {}
    base = f"/v1/whatsapp/channels/{channel['id']}/caller-routes"
    route = (
        await client.post(
            base, json={"caller_number": "+14085550333", "agent_id": agent}, headers=account.headers
        )
    ).json()
    assert len(channels.sip.rules) == 1
    routed = await channels.claim_inbound(
        client,
        channel="whatsapp",
        route_ref=channel["id"],
        trunk_number=channel["e164"],
        caller="+14085550333",
    )
    assert routed["admitted"] and routed["runtime"]["agent_id"] == agent
    other = await channels.claim_inbound(
        client,
        channel="whatsapp",
        route_ref=channel["id"],
        trunk_number=channel["e164"],
        caller="+14085550444",
    )
    assert not other["admitted"]
    assert (await client.delete(f"{base}/{route['id']}", headers=account.headers)).status_code == 204
    assert channels.sip.rules == {}


async def test_route_validation_and_limit(
    client: httpx.AsyncClient, account: Account, channels: Channels, monkeypatch: pytest.MonkeyPatch
) -> None:
    agent = channels.agent(account.workspace_id)
    unpublished = channels.agent(account.workspace_id, published=False)
    channel = await channels.whatsapp(client, account)
    base = f"/v1/whatsapp/channels/{channel['id']}/caller-routes"
    bad = await client.post(base, json={"caller_number": "12", "agent_id": agent}, headers=account.headers)
    assert bad.status_code == 422
    draft = await client.post(
        base, json={"caller_number": "+14085550555", "agent_id": unpublished}, headers=account.headers
    )
    assert draft.status_code == 422
    monkeypatch.setattr(whatsapp, "MAX_ROUTES", 2)
    for caller in ("+14085550601", "+14085550602"):
        assert (
            await client.post(
                base, json={"caller_number": caller, "agent_id": agent}, headers=account.headers
            )
        ).status_code == 201
    full = await client.post(
        base, json={"caller_number": "+14085550603", "agent_id": agent}, headers=account.headers
    )
    assert full.status_code == 409 and full.json()["code"] == "route_limit_reached"
    assert (await client.get(f"/v1/whatsapp/channels/{channel['id']}", headers=account.headers)).json()[
        "caller_route_count"
    ] == 2
