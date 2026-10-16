"""Stuck-call reaper (003 T050, FR-026, R16): queued past 60 s, heartbeat lost past 60 s, room
deleted, concurrency slot released, billed only for connected time."""

from __future__ import annotations

from app.calls import service as calls
from app.calls.jobs import reap_and_clean
from tests.runtime_support import Runtime, admitted_call, owner_sql, post_events


async def _reap(runtime: Runtime) -> dict[str, str]:
    result = await reap_and_clean(runtime.db, runtime.livekit, runtime.queue)
    return {r.call_id: r.outcome for r in result.reaped}


async def test_queued_without_a_worker_fails(runtime: Runtime) -> None:
    fresh = await admitted_call(runtime)
    stale = await admitted_call(runtime)
    owner_sql("update calls set created_at = now() - interval '61 seconds' where id = %s", (stale.call_id,))
    reaped = await _reap(runtime)
    assert reaped.get(stale.call_id) == "failed" and fresh.call_id not in reaped
    assert owner_sql("select diagnostic, billable_seconds from calls where id = %s", (stale.call_id,)) == [
        ("worker_unavailable", 0)
    ]
    assert f"call-{stale.call_id}" in runtime.livekit.deleted


async def test_claimed_web_call_where_the_caller_never_joined(runtime: Runtime) -> None:
    setup = await admitted_call(runtime)
    owner_sql(
        "update calls set created_at = now() - interval '70 seconds', "
        "claimed_at = now() - interval '65 seconds' "
        "where id = %s",
        (setup.call_id,),
    )
    assert (await _reap(runtime))[setup.call_id] == "failed"
    assert owner_sql("select diagnostic from calls where id = %s", (setup.call_id,)) == [
        ("caller_never_joined",)
    ]


async def test_silent_connected_call_is_ended_and_billed_to_last_heartbeat(runtime: Runtime) -> None:
    _, ws = await runtime.workspace(concurrency=1)
    setup = await admitted_call(runtime, ws)
    await post_events(runtime, setup.call_id, [setup.events.status("in_progress"), setup.events.usage()])
    owner_sql(
        "update calls set connected_at = now() - interval '3 minutes', "
        "last_heartbeat_at = now() - interval '61 seconds' where id = %s",
        (setup.call_id,),
    )
    # The slot is taken while the call is open...
    blocked = await calls.admit(
        runtime.db,
        calls.AdmissionRequest(ws, setup.agent.agent_id, "web", "inbound", version="draft"),
        catalog=runtime.catalog,
    )
    assert blocked.refusal is not None and blocked.refusal.code == "concurrency_limit"
    assert (await _reap(runtime))[setup.call_id] == "ended"
    row = owner_sql(
        "select status, disconnect_reason, diagnostic, billable_seconds from calls where id = %s",
        (setup.call_id,),
    )
    status, reason, diagnostic, billable = row[0]
    assert (status, reason, diagnostic) == ("ended", "error", "heartbeat_lost")
    assert 119 <= billable <= 121  # connected 3 min ago, last heard 61 s ago
    assert "run_pipeline" in runtime.queue.names()
    # ...and released once reaped.
    again = await calls.admit(
        runtime.db,
        calls.AdmissionRequest(ws, setup.agent.agent_id, "web", "inbound", version="draft"),
        catalog=runtime.catalog,
    )
    assert again.admitted


async def test_live_calls_with_recent_heartbeats_are_left_alone(runtime: Runtime) -> None:
    setup = await admitted_call(runtime)
    await post_events(runtime, setup.call_id, [setup.events.status("in_progress")])
    owner_sql("update calls set created_at = now() - interval '10 minutes' where id = %s", (setup.call_id,))
    assert setup.call_id not in await _reap(runtime)


async def test_ringing_call_without_heartbeat_fails(runtime: Runtime) -> None:
    setup = await admitted_call(runtime)
    await post_events(runtime, setup.call_id, [setup.events.status("ringing")])
    owner_sql(
        "update calls set last_heartbeat_at = now() - interval '90 seconds' where id = %s", (setup.call_id,)
    )
    assert (await _reap(runtime))[setup.call_id] == "failed"
    assert owner_sql("select diagnostic from calls where id = %s", (setup.call_id,)) == [("heartbeat_lost",)]
