"""The ``call_inbound`` webhook (010 T062, FR-031 to FR-033): variables applied; a timeout keeps
the defaults and is noted; ``decline`` is a failed call that is never billed; another
workspace's or an unpublished agent is ignored; private addresses are refused."""

from __future__ import annotations

import json
from collections.abc import Iterator

import httpx
import pytest
import respx

from app.webhooks_out import signing
from tests.conftest import Account
from tests.fakes.livekit_fake import Channels
from tests.runtime_support import owner_sql

HOOK = "https://crm.example.com/callwright"
PINNED = "https://93.184.216.34/callwright"  # tests resolve every public host to this address


@pytest.fixture
def receiver() -> Iterator[respx.MockRouter]:
    with respx.mock(assert_all_called=False) as router:
        yield router


async def _number(client: httpx.AsyncClient, account: Account, channels: Channels) -> tuple[dict, str]:  # type: ignore[type-arg]
    agent = channels.agent(account.workspace_id)
    number = await channels.number(client, account, inbound_agent_id=agent, inbound_webhook_url=HOOK)
    return number, agent


async def test_reply_variables_and_agent(
    client: httpx.AsyncClient, account: Account, channels: Channels, receiver: respx.MockRouter
) -> None:
    number, agent = await _number(client, account, channels)
    other = channels.agent(account.workspace_id)
    route = receiver.post(PINNED).respond(
        200,
        json={"agent_id": other, "dynamic_variables": {"customer_name": "Asha"}, "metadata": {"crm": "88"}},
    )
    claim = await channels.claim_inbound(
        client,
        channel="sip_inbound",
        route_ref=number["id"],
        trunk_number=number["e164"],
        caller="+14085550123",
    )
    assert claim["admitted"] and claim["runtime"]["agent_id"] == other
    assert claim["runtime"]["variables"]["customer_name"] == "Asha"
    request = route.calls.last.request
    sent = json.loads(request.content)
    assert sent["event"] == "call_inbound" and sent["call_id"] == claim["call_id"]
    assert sent["from_number"] == "+14085550123" and sent["to_number"] == number["e164"]
    assert sent["phone_number_id"] == number["id"] and sent["agent_id"] == agent
    assert request.headers["Callwright-Event"] == "call_inbound"
    assert signing.HEADER in request.headers and request.headers["host"] == "crm.example.com"
    assert owner_sql(
        "select metadata->>'crm', route_detail from calls where id = %s", (claim["call_id"],)
    ) == [("88", None)]


async def test_timeout_and_errors_keep_defaults(
    client: httpx.AsyncClient, account: Account, channels: Channels, receiver: respx.MockRouter
) -> None:
    number, agent = await _number(client, account, channels)
    receiver.post(PINNED).mock(side_effect=httpx.ReadTimeout("slow"))
    claim = await channels.claim_inbound(
        client, channel="sip_inbound", route_ref=number["id"], trunk_number=number["e164"]
    )
    assert claim["admitted"] and claim["runtime"]["agent_id"] == agent
    assert owner_sql("select route_detail from calls where id = %s", (claim["call_id"],)) == [
        ("inbound_webhook_failed:timeout",)
    ]
    for response, reason in (
        (httpx.Response(500), "http_500"),
        (httpx.Response(200, content=b"<html>"), "invalid_json"),
        (httpx.Response(200, content=b"x" * 20_000), "too_large"),
    ):
        receiver.post(PINNED).mock(return_value=response)
        claim = await channels.claim_inbound(
            client, channel="sip_inbound", route_ref=number["id"], trunk_number=number["e164"]
        )
        assert claim["admitted"]
        assert owner_sql("select route_detail from calls where id = %s", (claim["call_id"],)) == [
            (f"inbound_webhook_failed:{reason}",)
        ]


async def test_decline_is_not_billed(
    client: httpx.AsyncClient, account: Account, channels: Channels, receiver: respx.MockRouter
) -> None:
    number, _ = await _number(client, account, channels)
    receiver.post(PINNED).respond(200, json={"action": "decline"})
    claim = await channels.claim_inbound(
        client, channel="sip_inbound", route_ref=number["id"], trunk_number=number["e164"]
    )
    assert not claim["admitted"] and claim["refusal"]["diagnostic"] == "declined_by_webhook"
    assert owner_sql(
        "select status, billable_seconds, diagnostic, route_detail from calls where id = %s",
        (claim["call_id"],),
    ) == [("failed", 0, "declined_by_webhook", "declined_by_webhook")]
    await channels.runtime.run_jobs()
    assert owner_sql("select count(*) from call_costs where call_id = %s", (claim["call_id"],)) == [(0,)]


async def test_foreign_or_unpublished_agent_is_ignored(
    client: httpx.AsyncClient, account: Account, channels: Channels, receiver: respx.MockRouter
) -> None:
    from tests.conftest import make_workspace

    number, agent = await _number(client, account, channels)
    _, other_ws = await make_workspace(channels.app)
    foreign = channels.agent(other_ws)
    draft = channels.agent(account.workspace_id, published=False)
    for candidate in (foreign, draft, "not-an-id"):
        receiver.post(PINNED).respond(200, json={"agent_id": candidate})
        claim = await channels.claim_inbound(
            client, channel="sip_inbound", route_ref=number["id"], trunk_number=number["e164"]
        )
        assert claim["admitted"] and claim["runtime"]["agent_id"] == agent
        assert owner_sql("select route_detail from calls where id = %s", (claim["call_id"],)) == [
            ("inbound_webhook_agent_ignored",)
        ]


async def test_private_urls_are_refused(
    client: httpx.AsyncClient, account: Account, channels: Channels, receiver: respx.MockRouter
) -> None:
    number, _ = await _number(client, account, channels)
    refused = await client.patch(
        f"/v1/phone-numbers/{number['id']}",
        json={"inbound_webhook_url": "https://private.test.example/hook"},
        headers=account.headers,
    )
    assert refused.status_code == 422 and refused.json()["errors"][0]["pointer"] == "/inbound_webhook_url"
    owner_sql(
        "update phone_numbers set inbound_webhook_url = 'https://10.0.0.8/hook' where id = %s",
        (number["id"],),
    )
    claim = await channels.claim_inbound(
        client, channel="sip_inbound", route_ref=number["id"], trunk_number=number["e164"]
    )
    assert claim["admitted"]
    assert owner_sql("select route_detail from calls where id = %s", (claim["call_id"],)) == [
        ("inbound_webhook_failed:blocked_url",)
    ]
