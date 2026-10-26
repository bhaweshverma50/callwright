"""Money test (010 T028, FR-018): busy, no answer, ring timeout and failed outbound calls have
zero billable seconds, no charge, and send ``call_ended``."""

from __future__ import annotations

import httpx
import pytest

from tests.conftest import Account
from tests.fakes.livekit_fake import Channels, fresh_e164
from tests.runtime_support import SERVICE_HEADERS, Events, dispatch_metadata, owner_sql


@pytest.mark.parametrize(
    ("status", "diagnostic"),
    [("busy", "sip_486"), ("no_answer", "sip_480"), ("no_answer", "ring_timeout"), ("failed", "sip_404")],
)
async def test_unanswered_outcomes_are_free(
    client: httpx.AsyncClient, account: Account, channels: Channels, status: str, diagnostic: str
) -> None:
    agent = channels.agent(account.workspace_id, advanced={"webhook_url": "https://hooks.example.com/cw"})
    number = await channels.number(client, account, outbound_agent_id=agent)
    await channels.all_day(client, account)
    placed = await channels.place(
        client, account, to_number=fresh_e164(), from_number=number["e164"], ring_timeout_s=15
    )
    assert placed.status_code == 202
    call_id = placed.json()["call_id"]
    claim = await client.post(
        "/v1/internal/calls/claim",
        json={
            "job_id": f"AJ_{call_id[-6:]}",
            "room_name": f"call-{call_id}",
            "worker_id": "AW",
            "dispatch_metadata": dispatch_metadata(channels.runtime, call_id),
        },
        headers=SERVICE_HEADERS,
    )
    assert claim.json()["runtime"]["outbound_dial"]["ring_timeout_s"] == 15
    ev = Events()
    events = [ev.status("ringing")]
    ev.advance(15)
    events.append(
        ev.status(
            status, diagnostic=diagnostic, **({"disconnect_reason": "error"} if status == "failed" else {})
        )
    )
    posted = await client.post(
        f"/v1/internal/calls/{call_id}/events", json={"events": events}, headers=SERVICE_HEADERS
    )
    assert posted.status_code == 200, posted.text
    assert owner_sql("select status, billable_seconds, diagnostic from calls where id = %s", (call_id,)) == [
        (status, 0, diagnostic)
    ]
    channels.runtime.queue.clear()
    await channels.runtime.run_jobs()
    assert owner_sql("select count(*) from call_costs where call_id = %s", (call_id,)) == [(0,)]
    assert owner_sql(
        "select count(*) from credit_transactions where workspace_id = %s and type = 'call_charge'",
        (account.workspace_id,),
    ) == [(0,)]
    assert owner_sql(
        "select count(*) from webhook_deliveries where call_id = %s and event = 'call_ended'", (call_id,)
    ) == [(1,)]
