"""Calls on air now: ``GET /v1/calls/live`` (dashboard card, sidebar badge, pinned history rows).

The seeded workspace has one call in progress. These tests put a second call into ``ringing``
and a simulated call on air for the duration of a test and restore them afterwards, because the
seeded history is shared with the other 006 tests.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager

import httpx

from tests.calls_support import SeededCalls
from tests.runtime_support import owner_sql


def _in_progress(seeded: SeededCalls) -> str:
    rows = owner_sql(
        "select id from calls where workspace_id = %s and status = 'in_progress' and origin <> 'simulation'",
        (seeded.data.workspace_id,),
    )
    assert len(rows) == 1
    return str(rows[0][0])


@contextmanager
def _on_air(seeded: SeededCalls) -> Iterator[tuple[str, str, str]]:
    """A completed call set ringing, a simulated call set in progress and two lines on the live call."""
    live = _in_progress(seeded)
    ringing = seeded.data.call_ids[10]
    sim = seeded.data.simulation_call_ids[0]
    before = {
        cid: owner_sql(
            "select status, ringing_at, connected_at, ended_at, created_at from calls where id = %s", (cid,)
        )[0]
        for cid in (ringing, sim)
    }
    owner_sql(
        "update calls set status = 'ringing', ringing_at = now(), connected_at = null, ended_at = null, "
        "created_at = now() where id = %s",
        (ringing,),
    )
    owner_sql("update calls set status = 'in_progress', created_at = now() where id = %s", (sim,))
    for seq, (role, text) in enumerate(
        [("user", "Hi, I need to move my appointment."), ("assistant", "Sure, which day works for you?")],
        start=9000,
    ):
        owner_sql(
            "insert into call_events (workspace_id, call_id, seq, type, occurred_at, payload) "
            "values (%s, %s, %s, 'transcript_item', now(), %s::jsonb)",
            (
                seeded.data.workspace_id,
                live,
                seq,
                json.dumps({"item": {"type": "message", "role": role, "text": text}}),
            ),
        )
    try:
        yield live, ringing, sim
    finally:
        owner_sql("delete from call_events where call_id = %s and seq >= 9000", (live,))
        for cid, (status, ringing_at, connected_at, ended_at, created_at) in before.items():
            owner_sql(
                "update calls set status = %s, ringing_at = %s, connected_at = %s, ended_at = %s, "
                "created_at = %s where id = %s",
                (status, ringing_at, connected_at, ended_at, created_at, cid),
            )


async def test_live_calls_list_ringing_and_in_progress(
    client: httpx.AsyncClient, seeded_calls: SeededCalls
) -> None:
    with _on_air(seeded_calls) as (live, ringing, sim):
        res = await client.get("/v1/calls/live", headers=seeded_calls.a.headers)
        assert res.status_code == 200
        body = res.json()
        ids = [i["call_id"] for i in body["items"]]
        assert set(ids) == {live, ringing}
        assert sim not in ids
        assert body["count"] == 2
        assert body["server_time"]
        by_id = {i["call_id"]: i for i in body["items"]}
        assert by_id[ringing]["status"] == "ringing"
        assert by_id[ringing]["connected_at"] is None and by_id[ringing]["ringing_at"]
        assert by_id[ringing]["last_message"] is None
        on = by_id[live]
        assert on["status"] == "in_progress" and on["connected_at"]
        assert on["direction"] in ("inbound", "outbound")
        assert on["agent"]["name"] and on["agent"]["deleted"] is False
        assert on["last_message"] == {"role": "agent", "text": "Sure, which day works for you?"}
        # Newest first: the ringing call was created just now.
        assert ids[0] == ringing


async def test_live_calls_are_workspace_scoped(client: httpx.AsyncClient, seeded_calls: SeededCalls) -> None:
    with _on_air(seeded_calls):
        other = await client.get("/v1/calls/live", headers=seeded_calls.b.headers)
        assert other.status_code == 200
        assert other.json()["items"] == [] and other.json()["count"] == 0
    assert (await client.get("/v1/calls/live")).status_code == 401


async def test_list_items_carry_connected_at(client: httpx.AsyncClient, seeded_calls: SeededCalls) -> None:
    live = _in_progress(seeded_calls)
    body = (
        await client.get("/v1/calls", params={"status": "in_progress"}, headers=seeded_calls.a.headers)
    ).json()
    assert [i["call_id"] for i in body["items"]] == [live]
    assert body["items"][0]["connected_at"]
    failed = (
        await client.get(
            "/v1/calls", params={"status": "failed", "page_size": 100}, headers=seeded_calls.a.headers
        )
    ).json()
    assert all(i["connected_at"] is None for i in failed["items"])
