"""Recordings whose ``egress_ended`` webhook was lost are settled by asking LiveKit."""

from __future__ import annotations

from datetime import UTC, datetime

from app.calls.jobs import settle_recordings, start_recording_for
from tests.runtime_support import Runtime, admitted_call, owner_sql


async def _ended_recording(runtime: Runtime, ended_ago_s: int) -> tuple[str, str]:
    setup = await admitted_call(runtime)
    assert (
        await start_recording_for(
            runtime.db, runtime.livekit, "callwright-recordings", setup.workspace_id, setup.call_id
        )
        == "started"
    )
    owner_sql(
        "update calls set ended_at = now() - make_interval(secs => %s) where id = %s",
        (ended_ago_s, setup.call_id),
    )
    egress_id = owner_sql("select egress_id from calls where id = %s", (setup.call_id,))[0][0]
    return setup.call_id, egress_id


def _status(call_id: str) -> tuple[str, str | None]:
    row = owner_sql("select recording_status, recording_key from calls where id = %s", (call_id,))[0]
    return row[0], row[1]


async def test_a_finished_egress_marks_the_recording_available(runtime: Runtime) -> None:
    call_id, egress_id = await _ended_recording(runtime, 600)
    key = f"recordings/ws/{call_id}.mp4"
    runtime.livekit.egress_infos[egress_id] = {
        "egressId": egress_id,
        "status": "EGRESS_COMPLETE",
        "fileResults": [{"filename": key}],
    }
    assert await settle_recordings(runtime.db, runtime.livekit) >= 1
    assert _status(call_id) == ("available", key)


async def test_running_recent_and_unreachable_egresses_are_left_alone(runtime: Runtime) -> None:
    active_id, active_egress = await _ended_recording(runtime, 600)
    runtime.livekit.egress_infos[active_egress] = {"egressId": active_egress, "status": "EGRESS_ACTIVE"}
    recent_id, _ = await _ended_recording(runtime, 10)
    await settle_recordings(runtime.db, runtime.livekit)
    assert _status(active_id)[0] == "recording"
    assert _status(recent_id)[0] == "recording"
    runtime.livekit.fail_next.add("egress_info")
    await settle_recordings(runtime.db, runtime.livekit)
    assert _status(active_id)[0] == "recording"


async def test_an_egress_livekit_forgot_fails_after_half_an_hour(runtime: Runtime) -> None:
    young_id, _ = await _ended_recording(runtime, 600)
    old_id, _ = await _ended_recording(runtime, 3600)
    await settle_recordings(runtime.db, runtime.livekit, now=datetime.now(UTC))
    assert _status(young_id)[0] == "recording"
    assert _status(old_id)[0] == "failed"
