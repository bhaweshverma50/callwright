"""Outbound policies (010 T026): same number, number not active or draining, no outbound agent,
unpublished agent, and the per-workspace rate limit; nothing is admitted or dialled."""

from __future__ import annotations

import asyncio

import httpx

from tests.conftest import Account
from tests.fakes.livekit_fake import Channels, fresh_e164
from tests.runtime_support import owner_sql


def _calls(workspace_id: str) -> int:
    return int(owner_sql("select count(*) from calls where workspace_id = %s", (workspace_id,))[0][0])


async def test_policies_refuse_before_admission(
    client: httpx.AsyncClient, account: Account, channels: Channels
) -> None:
    number, _ = await channels.outbound_ready(client, account)
    to = fresh_e164()
    same = await channels.place(client, account, to_number=number["e164"], from_number=number["e164"])
    assert same.status_code == 422 and same.json()["code"] == "same_number"

    unknown = await channels.place(client, account, to_number=to, from_number=fresh_e164())
    assert unknown.status_code == 422 and unknown.json()["errors"][0]["pointer"] == "/from_number"

    for status in ("error", "draining", "provisioning"):
        owner_sql("update phone_numbers set status = %s where id = %s", (status, number["id"]))
        refused = await channels.place(client, account, to_number=to, from_number=number["e164"])
        assert refused.status_code == 409 and refused.json()["code"] == "from_number_not_active", status
    owner_sql("update phone_numbers set status = 'active' where id = %s", (number["id"],))

    bare = await channels.number(client, account)
    no_agent = await channels.place(client, account, to_number=to, from_number=bare["e164"])
    assert no_agent.status_code == 409 and no_agent.json()["code"] == "no_outbound_agent"

    draft_only = channels.agent(account.workspace_id, published=False)
    unpublished = await channels.place(
        client, account, to_number=to, from_number=number["e164"], agent_id=draft_only
    )
    assert unpublished.status_code == 409 and unpublished.json()["code"] == "agent_not_published"
    foreign = await channels.place(
        client, account, to_number=to, from_number=number["e164"], agent_id="agt_01ARZ3NDEKTSV4RRFFQ69G5FAV"
    )
    assert foreign.status_code == 422
    assert _calls(account.workspace_id) == 0


async def test_rate_limit_is_per_workspace(
    client: httpx.AsyncClient, account: Account, channels: Channels
) -> None:
    number, _ = await channels.outbound_ready(client, account)
    responses = await asyncio.gather(
        *(
            channels.place(client, account, to_number=number["e164"], from_number=number["e164"])
            for _ in range(40)
        )
    )
    limited = [r for r in responses if r.status_code == 429]
    assert limited and all(r.status_code in (422, 429) for r in responses)
    assert sum(r.status_code == 422 for r in responses) >= 20  # the burst passes
    assert int(limited[0].headers["Retry-After"]) >= 1 and limited[0].json()["code"] == "rate_limited"
