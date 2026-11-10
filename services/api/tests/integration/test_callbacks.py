"""Scheduled callbacks (011): the agent books one on a phone call, the cron places it through
010's outbound path (policies, admission, idempotency), refusals the agent can relay, the public
API, cancel and row-level security."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from fastapi import FastAPI
from sqlalchemy import text

from app.callbacks.service import place_due
from app.outbound.service import OutboundDeps
from tests.conftest import Account, signup
from tests.fakes.livekit_fake import Channels, fresh_e164
from tests.runtime_support import SERVICE_HEADERS, owner_sql


def deps(app: FastAPI) -> OutboundDeps:
    state = app.state
    return OutboundDeps(
        db=state.db,
        settings=state.settings,
        sip=state.sip,
        livekit=state.livekit,
        catalog=state.adapter_catalog,
        jobs=getattr(state, "jobs", None),
        redis=state.redis,
    )


async def inbound_call(
    client: httpx.AsyncClient, account: Account, channels: Channels, caller: str | None = None
) -> tuple[str, dict[str, Any], str, str]:
    """A live inbound phone call: (call id, number, agent id, caller number)."""
    agent = channels.agent(account.workspace_id)
    number = await channels.number(client, account, inbound_agent_id=agent)
    await channels.all_day(client, account)
    caller = caller or fresh_e164()
    claim = await channels.claim_inbound(
        client, channel="sip_inbound", route_ref=number["id"], trunk_number=number["e164"], caller=caller
    )
    assert claim["admitted"], claim
    return str(claim["call_id"]), number, agent, caller


async def book(client: httpx.AsyncClient, call_id: str, **body: Any) -> httpx.Response:
    return await client.post(f"/v1/internal/calls/{call_id}/callbacks", json=body, headers=SERVICE_HEADERS)


def scheduled_at(callback: dict[str, Any]) -> datetime:
    return datetime.fromisoformat(callback["scheduled_at"].replace("Z", "+00:00"))


async def test_agent_books_on_inbound_call_and_cron_places_it_once(
    app: FastAPI, client: httpx.AsyncClient, account: Account, channels: Channels
) -> None:
    call_id, number, agent, caller = await inbound_call(client, account, channels)
    owner_sql(
        "update calls set dynamic_variables = dynamic_variables || %s::jsonb where id = %s",
        ('{"customer_name": "Asha"}', call_id),
    )
    first = await book(client, call_id, in_minutes=60, note="Caller is in a meeting; finish rebooking")
    assert first.status_code == 201, first.text
    booked = first.json()
    assert booked["scheduled"] and not booked["mocked"] and not booked["rescheduled"]
    assert booked["timezone"] == "America/Los_Angeles"
    assert booked["spoken_time"].endswith(("am", "pm"))

    tomorrow = (datetime.now(UTC).astimezone() + timedelta(days=1)).date().isoformat()
    moved = await book(client, call_id, at=f"{tomorrow}T17:00", note="Finish rebooking the cleaning")
    assert moved.status_code == 201, moved.text
    assert moved.json()["rescheduled"] and moved.json()["callback_id"] == booked["callback_id"]
    assert moved.json()["local_time"] == f"{tomorrow}T17:00"

    listed = await client.get(f"/v1/callbacks?source_call_id={call_id}", headers=account.headers)
    assert listed.status_code == 200 and listed.json()["total"] == 1
    callback = listed.json()["items"][0]
    assert callback["status"] == "scheduled" and callback["created_via"] == "agent"
    assert callback["to_number"] == caller and callback["from_number"] == number["e164"]
    assert callback["agent_id"] == agent and callback["agent_name"]
    assert callback["local_time"] == f"{tomorrow}T17:00:00"
    carried = callback["dynamic_variables"]
    assert carried["customer_name"] == "Asha" and carried["callback_note"] == "Finish rebooking the cleaning"
    assert not {"call_id", "timezone", "current_time", "user_number"} & set(carried)

    at = scheduled_at(callback)
    assert await place_due(deps(app), now=at - timedelta(minutes=1)) == 0  # not due yet
    assert await place_due(deps(app), now=at + timedelta(seconds=5)) == 1
    placed = (await client.get(f"/v1/callbacks/{callback['id']}", headers=account.headers)).json()
    assert placed["status"] == "placed" and placed["call_id"] and placed["attempts"] == 1
    row = owner_sql(
        "select direction, channel, to_number, from_number, agent_id, idempotency_key, metadata, "
        "dynamic_variables->>'callback_note' from calls where id = %s",
        (placed["call_id"],),
    )[0]
    assert row[:6] == (
        "outbound",
        "sip_outbound",
        caller,
        number["e164"],
        agent,
        f"callback:{callback['id']}",
    )
    assert row[6] == {"callback_id": callback["id"], "source_call_id": call_id}
    assert row[7] == "Finish rebooking the cleaning"
    assert [m for _, _, m in channels.runtime.livekit.dispatches if m.get("call_id") == placed["call_id"]]

    # A run that died mid-dial is retried safely: the idempotency key finds the same call.
    owner_sql(
        "update scheduled_callbacks set status = 'placing', updated_at = now() - interval '5 minutes' "
        "where id = %s",
        (callback["id"],),
    )
    assert await place_due(deps(app), now=at + timedelta(minutes=3)) == 1
    again = (await client.get(f"/v1/callbacks/{callback['id']}", headers=account.headers)).json()
    assert again["status"] == "placed" and again["call_id"] == placed["call_id"]
    outbound_calls = owner_sql(
        "select count(*) from calls where workspace_id = %s and direction = 'outbound'",
        (account.workspace_id,),
    )
    assert outbound_calls == [(1,)]


async def test_booking_refusals_the_agent_can_relay(
    client: httpx.AsyncClient, account: Account, channels: Channels
) -> None:
    call_id, _, _, caller = await inbound_call(client, account, channels)

    past = await book(client, call_id, at="2020-01-01T09:00", note="")
    assert past.status_code == 422 and past.json()["reason"] == "invalid_time"
    garbled = await book(client, call_id, at="tomorrow at five")
    assert garbled.status_code == 422 and garbled.json()["reason"] == "invalid_time"
    both = await book(client, call_id, at="2030-01-01T09:00", in_minutes=5)
    assert both.status_code == 422

    await channels.all_day(client, account, {"start": "09:00", "end": "10:00"})
    tomorrow = (datetime.now(UTC) + timedelta(days=2)).date().isoformat()
    late = await book(client, call_id, at=f"{tomorrow}T20:00")
    assert late.status_code == 422, late.text
    body = late.json()
    assert body["reason"] == "outside_calling_hours" and body["next_allowed_at"]
    assert "9:00 am" in body["next_allowed_spoken"] and "9:00 am" in body["detail"]
    await channels.all_day(client, account)

    await client.post("/v1/dnc-entries", json={"number": caller}, headers=account.headers)
    listed = await book(client, call_id, in_minutes=30)
    assert listed.status_code == 422 and listed.json()["reason"] == "dnc_listed"

    owner_sql("update calls set channel = 'web' where id = %s", (call_id,))
    web = await book(client, call_id, in_minutes=30)
    assert web.status_code == 422 and web.json()["reason"] == "channel_unsupported"
    assert "phone calls" in web.json()["detail"]

    owner_sql("update calls set origin = 'simulation' where id = %s", (call_id,))
    simulated = await book(client, call_id, in_minutes=30, note="sim")
    assert simulated.status_code == 200 and simulated.json()["mocked"]
    assert simulated.json()["callback_id"] is None

    assert owner_sql(
        "select count(*) from scheduled_callbacks where workspace_id = %s", (account.workspace_id,)
    ) == [(0,)]
    assert (await book(client, "call_01ARZ3NDEKTSV4RRFFQ69G5FAV", in_minutes=30)).status_code == 404
    unauth = await client.post(f"/v1/internal/calls/{call_id}/callbacks", json={"in_minutes": 30})
    assert unauth.status_code == 401


async def create(client: httpx.AsyncClient, account: Account, **body: Any) -> httpx.Response:
    return await client.post("/v1/callbacks", json=body, headers=account.headers)


async def test_public_create_cancel_and_cron_refusals(
    app: FastAPI, client: httpx.AsyncClient, account: Account, channels: Channels
) -> None:
    number, agent = await channels.outbound_ready(client, account)
    soon = datetime.now(UTC) + timedelta(minutes=5)

    def body(**extra: Any) -> dict[str, Any]:
        return {
            "to_number": fresh_e164(),
            "from_number": number["e164"],
            "scheduled_at": soon.isoformat(),
            "note": "Follow up",
            **extra,
        }

    past = await create(client, account, **body(scheduled_at="2020-01-01T09:00:00Z"))
    assert past.status_code == 422 and past.json()["code"] == "invalid_time"
    naive = await create(client, account, **body(scheduled_at="2030-01-01T09:00:00"))
    assert naive.status_code == 422
    blocked_to = fresh_e164()
    await client.post("/v1/dnc-entries", json={"number": blocked_to}, headers=account.headers)
    dnc = await create(client, account, **body(to_number=blocked_to))
    assert dnc.status_code == 422 and dnc.json()["reason"] == "dnc_listed"
    await channels.all_day(client, account, None)
    hours = await create(client, account, **body())
    assert hours.status_code == 422 and hours.json()["reason"] == "outside_calling_hours"
    await channels.all_day(client, account)
    assert owner_sql(
        "select count(*) from outbound_policy_decisions where workspace_id = %s", (account.workspace_id,)
    ) == [(0,)]

    made = [await create(client, account, **body()) for _ in range(5)]
    assert all(r.status_code == 201 for r in made), made[0].text
    a, b, c, d, e = (r.json() for r in made)
    assert a["created_via"] == "api" and a["agent_id"] == agent and a["created_by_user_id"]
    assert a["dynamic_variables"]["callback_note"] == "Follow up"

    cancelled = await client.post(f"/v1/callbacks/{a['id']}/cancel", headers=account.headers)
    assert cancelled.status_code == 200 and cancelled.json()["status"] == "cancelled"
    twice = await client.post(f"/v1/callbacks/{a['id']}/cancel", headers=account.headers)
    assert twice.status_code == 200

    # After booking: b's number goes on the do-not-call list and c's agent loses its version;
    # d and e are placed.
    await client.post("/v1/dnc-entries", json={"number": b["to_number"]}, headers=account.headers)
    unpublished = channels.agent(account.workspace_id, published=False)
    owner_sql("update scheduled_callbacks set agent_id = %s where id = %s", (unpublished, c["id"]))
    assert await place_due(deps(app), now=soon + timedelta(seconds=5)) == 2
    got = {
        cb["id"]: cb
        for cb in (await client.get("/v1/callbacks?page_size=100", headers=account.headers)).json()["items"]
    }
    assert got[a["id"]]["status"] == "cancelled"
    assert (got[b["id"]]["status"], got[b["id"]]["failure_reason"]) == ("failed", "dnc_listed")
    assert (got[c["id"]]["status"], got[c["id"]]["failure_reason"]) == ("failed", "agent_not_published")
    assert got[d["id"]]["status"] == got[e["id"]]["status"] == "placed"
    decisions = owner_sql(
        "select reason, requested_by from outbound_policy_decisions where workspace_id = %s",
        (account.workspace_id,),
    )
    assert decisions == [("dnc_listed", f"callback:{b['id']}")]
    placed_cancel = await client.post(f"/v1/callbacks/{e['id']}/cancel", headers=account.headers)
    assert placed_cancel.status_code == 409 and placed_cancel.json()["code"] == "callback_not_scheduled"

    scheduled = await client.get("/v1/callbacks?status=failed", headers=account.headers)
    assert scheduled.json()["total"] == 2

    # Calling hours closed between booking and the dial: failed with the reason, decision logged.
    closed = (await create(client, account, **body())).json()
    await channels.all_day(client, account, None)
    assert await place_due(deps(app), now=soon + timedelta(minutes=1)) == 0
    after = (await client.get(f"/v1/callbacks/{closed['id']}", headers=account.headers)).json()
    assert (after["status"], after["failure_reason"]) == ("failed", "outside_calling_hours")
    assert "outside calling hours" in after["failure_detail"]


async def test_missed_and_busy(
    app: FastAPI, client: httpx.AsyncClient, account: Account, channels: Channels
) -> None:
    await inbound_call(client, account, channels)  # holds the only call slot
    number, _ = await channels.outbound_ready(client, account)
    soon = datetime.now(UTC) + timedelta(minutes=5)
    made = await create(
        client, account, to_number=fresh_e164(), from_number=number["e164"], scheduled_at=soon.isoformat()
    )
    callback_id = made.json()["id"]
    owner_sql("update workspaces set concurrency_limit = 1 where id = %s", (account.workspace_id,))
    assert await place_due(deps(app), now=soon + timedelta(seconds=5)) == 0
    waiting = (await client.get(f"/v1/callbacks/{callback_id}", headers=account.headers)).json()
    assert waiting["status"] == "scheduled" and waiting["attempts"] == 0
    assert await place_due(deps(app), now=soon + timedelta(minutes=31)) == 0
    missed = (await client.get(f"/v1/callbacks/{callback_id}", headers=account.headers)).json()
    assert (missed["status"], missed["failure_reason"]) == ("failed", "missed")
    owner_sql("update workspaces set concurrency_limit = 5 where id = %s", (account.workspace_id,))


async def test_callbacks_are_isolated(
    app: FastAPI, client: httpx.AsyncClient, account: Account, channels: Channels
) -> None:
    number, _ = await channels.outbound_ready(client, account)
    made = await create(
        client,
        account,
        to_number=fresh_e164(),
        from_number=number["e164"],
        scheduled_at=(datetime.now(UTC) + timedelta(hours=2)).isoformat(),
    )
    assert made.status_code == 201
    other = await signup(client, app)
    path = f"/v1/callbacks/{made.json()['id']}"
    assert (await client.get(path, headers=other.headers)).status_code == 404
    assert (await client.post(f"{path}/cancel", headers=other.headers)).status_code == 404
    assert (await client.get("/v1/callbacks", headers=other.headers)).json()["total"] == 0
    db = app.state.db
    async with db.transaction(workspace_id=other.workspace_id) as session:
        seen = (
            await session.execute(
                text("select count(*) from scheduled_callbacks where workspace_id = :ws"),
                {"ws": account.workspace_id},
            )
        ).scalar_one()
    assert seen == 0
    async with db.transaction() as session:
        assert (await session.execute(text("select count(*) from scheduled_callbacks"))).scalar_one() == 0
