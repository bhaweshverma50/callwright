"""Money test (010 T027, research R7): 100 replays with one key place one call and one charge;
the same key with another body is refused; a missing key is a 400."""

from __future__ import annotations

import asyncio

import httpx

from tests.conftest import Account
from tests.fakes.livekit_fake import Channels, fresh_e164
from tests.runtime_support import SERVICE_HEADERS, Events, dispatch_metadata, owner_sql


async def test_one_key_one_call_one_charge(
    client: httpx.AsyncClient, account: Account, channels: Channels
) -> None:
    number, _ = await channels.outbound_ready(client, account)
    body = {
        "to_number": fresh_e164(),
        "from_number": number["e164"],
        "dynamic_variables": {"customer_name": "Asha"},
    }
    key = "outbound-replay-0001"
    first = await channels.place(client, account, key, **body)
    assert first.status_code == 202, first.text
    call_id = first.json()["call_id"]
    replays = []
    for _ in range(11):  # batches of 9 stay under the 20-request burst
        batch = await asyncio.gather(*(channels.place(client, account, key, **body) for _ in range(9)))
        replays.extend(batch)
        await asyncio.sleep(1.0)
    assert len(replays) == 99
    assert {r.status_code for r in replays} == {202}
    assert {r.json()["call_id"] for r in replays} == {call_id}
    assert all(r.json()["idempotent_replay"] for r in replays)
    assert owner_sql("select count(*) from calls where workspace_id = %s", (account.workspace_id,)) == [(1,)]
    dispatches = [m for _, _, m in channels.runtime.livekit.dispatches if m.get("call_id") == call_id]
    assert len(dispatches) == 1

    reused = await channels.place(client, account, key, **{**body, "to_number": fresh_e164()})
    assert reused.status_code == 422 and reused.json()["code"] == "idempotency_key_reused"
    missing = await client.post("/v1/outbound-calls", json=body, headers=account.headers)
    assert missing.status_code == 400

    # The call connects, talks for 30 s and ends: exactly one call_charge.
    claim = await client.post(
        "/v1/internal/calls/claim",
        json={
            "job_id": "AJ_idem",
            "room_name": f"call-{call_id}",
            "worker_id": "AW",
            "dispatch_metadata": dispatch_metadata(channels.runtime, call_id),
        },
        headers=SERVICE_HEADERS,
    )
    assert claim.status_code == 200 and claim.json()["admitted"]
    dial = claim.json()["runtime"]["outbound_dial"]
    assert dial["to_number"] == body["to_number"] and dial["from_number"] == number["e164"]
    assert dial["ring_timeout_s"] == 30 and dial["sip_trunk_id"].startswith("ST_")
    ev = Events()
    batch = [ev.status("ringing"), ev.status("in_progress"), ev.usage()]
    ev.advance(30)
    batch.append(ev.status("ended", disconnect_reason="user_hangup"))
    posted = await client.post(
        f"/v1/internal/calls/{call_id}/events", json={"events": batch}, headers=SERVICE_HEADERS
    )
    assert posted.status_code == 200
    await channels.runtime.run_jobs()
    charges = owner_sql(
        "select count(*) from credit_transactions where workspace_id = %s and type = 'call_charge'",
        (account.workspace_id,),
    )
    assert charges == [(1,)]
