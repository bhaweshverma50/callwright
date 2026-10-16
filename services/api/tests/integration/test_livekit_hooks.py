"""LiveKit webhooks (003 T076): ``egress_ended`` sets recording status and key; ``room_finished``
closes an open call with ``error``."""

from __future__ import annotations

import json
from typing import Any

import httpx
from fastapi import FastAPI

from app.calls.jobs import start_recording_for
from app.core.livekit import sign_webhook
from tests.runtime_support import Runtime, admitted_call, owner_sql, post_events


async def send(app: FastAPI, client: httpx.AsyncClient, event: dict[str, Any]) -> httpx.Response:
    body = json.dumps({"id": "EV", "createdAt": 1760600000, **event})
    s = app.state.settings
    token = sign_webhook(s.livekit_api_key.get_secret_value(), s.livekit_api_secret.get_secret_value(), body)
    return await client.post(
        "/v1/livekit/webhook",
        content=body,
        headers={"Authorization": token, "Content-Type": "application/webhook+json"},
    )


async def _recording(runtime: Runtime) -> tuple[str, str]:
    setup = await admitted_call(runtime)
    outcome = await start_recording_for(
        runtime.db, runtime.livekit, "callwright-recordings", setup.workspace_id, setup.call_id
    )
    assert outcome == "started"
    egress_id = owner_sql("select egress_id from calls where id = %s", (setup.call_id,))[0][0]
    return setup.call_id, egress_id


async def test_egress_lifecycle_sets_status_and_key(
    app: FastAPI, client: httpx.AsyncClient, runtime: Runtime
) -> None:
    call_id, egress_id = await _recording(runtime)
    room, target = runtime.livekit.egresses[-1]
    assert room == f"call-{call_id}" and target.key.endswith(f"/{call_id}.mp4")
    assert target.bucket == "callwright-recordings"
    started = await send(app, client, {"event": "egress_started", "egressInfo": {"egressId": egress_id}})
    assert started.status_code == 200
    assert owner_sql("select recording_status from calls where id = %s", (call_id,)) == [("recording",)]
    ended = await send(
        app,
        client,
        {
            "event": "egress_ended",
            "egressInfo": {
                "egressId": egress_id,
                "roomName": f"call-{call_id}",
                "status": "EGRESS_COMPLETE",
                "fileResults": [{"filename": target.key, "duration": "31000000000", "size": "250000"}],
            },
        },
    )
    assert ended.status_code == 200
    assert owner_sql("select recording_status, recording_key from calls where id = %s", (call_id,)) == [
        ("available", target.key)
    ]
    # Repeats are harmless.
    assert (
        await send(app, client, {"event": "egress_started", "egressInfo": {"egressId": egress_id}})
    ).status_code == 200
    assert owner_sql("select recording_status from calls where id = %s", (call_id,)) == [("available",)]


async def test_failed_egress_is_recording_unavailable(
    app: FastAPI, client: httpx.AsyncClient, runtime: Runtime
) -> None:
    call_id, egress_id = await _recording(runtime)
    await send(
        app,
        client,
        {
            "event": "egress_ended",
            "egressInfo": {"egressId": egress_id, "status": "EGRESS_FAILED", "error": "s3"},
        },
    )
    assert owner_sql("select recording_status from calls where id = %s", (call_id,)) == [("failed",)]


async def test_room_finished_ends_an_open_call(
    app: FastAPI, client: httpx.AsyncClient, runtime: Runtime
) -> None:
    setup = await admitted_call(runtime)
    await post_events(runtime, setup.call_id, [setup.events.status("in_progress")])
    response = await send(app, client, {"event": "room_finished", "room": {"name": f"call-{setup.call_id}"}})
    assert response.status_code == 200
    assert owner_sql(
        "select status, disconnect_reason, diagnostic from calls where id = %s", (setup.call_id,)
    ) == [("ended", "error", "room_finished")]
    assert "run_pipeline" in runtime.queue.names()
    # A second room_finished (or one after the worker's own end) changes nothing.
    await send(app, client, {"event": "room_finished", "room": {"name": f"call-{setup.call_id}"}})
    assert owner_sql("select disconnect_reason from calls where id = %s", (setup.call_id,)) == [("error",)]


async def test_room_finished_after_worker_end_keeps_the_reason(
    app: FastAPI, client: httpx.AsyncClient, runtime: Runtime
) -> None:
    setup = await admitted_call(runtime)
    ev = setup.events
    await post_events(
        runtime,
        setup.call_id,
        [ev.status("in_progress"), ev.status("ended", disconnect_reason="user_hangup")],
    )
    await send(app, client, {"event": "room_finished", "room": {"name": f"call-{setup.call_id}"}})
    assert owner_sql("select disconnect_reason from calls where id = %s", (setup.call_id,)) == [
        ("user_hangup",)
    ]


async def test_room_finished_before_connection_fails_the_call(
    app: FastAPI, client: httpx.AsyncClient, runtime: Runtime
) -> None:
    setup = await admitted_call(runtime)
    await send(app, client, {"event": "room_finished", "room": {"name": f"call-{setup.call_id}"}})
    assert owner_sql("select status, billable_seconds from calls where id = %s", (setup.call_id,)) == [
        ("failed", 0)
    ]
