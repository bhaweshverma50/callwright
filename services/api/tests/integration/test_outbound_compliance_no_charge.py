"""Money test (010 T073, FR-034): ``dnc_listed`` and ``outside_calling_hours`` blocks return 422
with the reason, create no call, no dispatch and no charge, write one policy decision, and are
not stored against the Idempotency-Key (a retry after the fix dials once). DNC wins when both
apply."""

from __future__ import annotations

import httpx

from tests.conftest import Account
from tests.fakes.livekit_fake import Channels, fresh_e164
from tests.runtime_support import owner_sql


def _state(workspace_id: str) -> tuple[int, int, int]:
    calls = owner_sql("select count(*) from calls where workspace_id = %s", (workspace_id,))[0][0]
    decisions = owner_sql(
        "select count(*) from outbound_policy_decisions where workspace_id = %s", (workspace_id,)
    )[0][0]
    charges = owner_sql(
        "select count(*) from credit_transactions where workspace_id = %s and type = 'call_charge'",
        (workspace_id,),
    )[0][0]
    return int(calls), int(decisions), int(charges)


async def test_blocks_create_nothing_and_retry_dials_once(
    client: httpx.AsyncClient, account: Account, channels: Channels
) -> None:
    number, agent = await channels.outbound_ready(client, account)
    to = fresh_e164()
    body = {"to_number": to, "from_number": number["e164"]}
    entry = (await client.post("/v1/dnc-entries", json={"number": to}, headers=account.headers)).json()
    await channels.all_day(client, account, None)  # outside hours as well: DNC is reported
    dispatches = len(channels.runtime.livekit.dispatches)

    key = "compliance-retry-0001"
    blocked = await channels.place(client, account, key, **body)
    assert blocked.status_code == 422 and blocked.json()["reason"] == "dnc_listed"
    assert _state(account.workspace_id) == (0, 1, 0)
    assert len(channels.runtime.livekit.dispatches) == dispatches
    row = owner_sql(
        "select reason, to_number, from_number, phone_number_id, agent_id, requested_by, idempotency_key, "
        "dnc_entry_id, dnc_e164 from outbound_policy_decisions where workspace_id = %s",
        (account.workspace_id,),
    )
    assert row == [
        ("dnc_listed", to, number["e164"], number["id"], agent, account.user_id, key, entry["id"], to)
    ]

    await client.delete(f"/v1/dnc-entries/{entry['id']}", headers=account.headers)
    hours = await channels.place(client, account, key, **body)
    assert hours.status_code == 422 and hours.json()["reason"] == "outside_calling_hours"
    assert _state(account.workspace_id) == (0, 2, 0)

    tz = await channels.place(client, account, key, **{**body, "recipient_timezone": "Asia/Kolkata"})
    assert tz.status_code == 422  # still no window on any day, in any zone

    await channels.all_day(client, account)
    placed = await channels.place(client, account, key, **body)
    assert placed.status_code == 202, placed.text
    again = await channels.place(client, account, key, **body)
    assert again.status_code == 202 and again.json()["call_id"] == placed.json()["call_id"]
    assert again.json()["idempotent_replay"] is True
    calls, decisions, charges = _state(account.workspace_id)
    assert (calls, decisions, charges) == (1, 3, 0)
    assert len(channels.runtime.livekit.dispatches) == dispatches + 1


async def test_unknown_zone_blocks_and_override_allows(
    client: httpx.AsyncClient, account: Account, channels: Channels
) -> None:
    number, _ = await channels.outbound_ready(client, account)
    global_number = "+882345678901"  # international networks: no timezone
    blocked = await channels.place(client, account, to_number=global_number, from_number=number["e164"])
    assert blocked.status_code == 422
    problem = blocked.json()
    assert problem["reason"] == "outside_calling_hours" and problem["timezone_source"] == "unknown"
    assert problem["recipient_timezones"] == [] and problem["next_allowed_at"] is None
    assert "recipient_timezone" in problem["detail"]
    allowed = await channels.place(
        client, account, to_number=global_number, from_number=number["e164"], recipient_timezone="Europe/Berlin"
    )
    assert allowed.status_code == 202, allowed.text
    assert allowed.json()["timezone_source"] == "override"
