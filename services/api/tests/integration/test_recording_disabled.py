"""Recording off (003 T112, FR-044, SC-010): no egress, ``not_recorded`` even if an egress webhook
arrives, transcript, turns, usage and latency still stored, charged and completed without a
warning."""

from __future__ import annotations

import json

import httpx
from fastapi import FastAPI

from app.calls import pipeline
from app.calls.jobs import start_recording_for
from app.core.livekit import sign_webhook
from tests.runtime_support import Runtime, agent_config, ended_call, owner_sql


async def test_recording_off_end_to_end(app: FastAPI, client: httpx.AsyncClient, runtime: Runtime) -> None:
    setup = await ended_call(runtime, config=agent_config(advanced={"recording": "off"}))
    call_id = setup.call_id
    egresses_before = len(runtime.livekit.egresses)
    assert (
        await start_recording_for(
            runtime.db, runtime.livekit, "callwright-recordings", setup.workspace_id, call_id
        )
        == "not_recorded"
    )
    assert len(runtime.livekit.egresses) == egresses_before

    # A stray egress webhook for the room is ignored.
    body = json.dumps(
        {
            "event": "egress_ended",
            "id": "EV",
            "createdAt": 1,
            "egressInfo": {
                "egressId": "EG_stray",
                "roomName": f"call-{call_id}",
                "status": "EGRESS_COMPLETE",
            },
        }
    )
    s = app.state.settings
    token = sign_webhook(s.livekit_api_key.get_secret_value(), s.livekit_api_secret.get_secret_value(), body)
    hook = await client.post("/v1/livekit/webhook", content=body, headers={"Authorization": token})
    assert hook.status_code == 200

    await pipeline.run(runtime.db, setup.workspace_id, call_id, catalog=runtime.catalog)
    row = owner_sql(
        "select recording_enabled, recording_status, egress_id, recording_key, status, pipeline_status, "
        "pipeline_warnings, usage_seq > 0, latency_stats is not null, "
        "jsonb_array_length(transcript->'items') "
        "from calls where id = %s",
        (call_id,),
    )
    assert row == [(False, "not_recorded", None, None, "completed", "done", [], True, True, 7)]
    assert owner_sql("select count(*) from call_events where call_id = %s and type = 'turn'", (call_id,)) == [
        (4,)
    ]
    assert owner_sql("select count(*) from credit_transactions where call_id = %s", (call_id,)) == [(1,)]
