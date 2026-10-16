"""Recording off (003 T112, FR-044, SC-010): no egress, ``not_recorded`` even if an egress webhook
arrives, transcript, turns, usage and latency still stored, charged and completed without a
warning, and ``recording_state()`` returns ``not_recorded`` with no URL."""

from __future__ import annotations

import json

import httpx
from fastapi import FastAPI
from sqlalchemy import select

from app.calls import pipeline
from app.calls import service as calls
from app.calls.jobs import start_recording_for
from app.calls.models import Call
from app.core.livekit import sign_webhook
from tests.runtime_support import Runtime, agent_config, ended_call, owner_sql


class Signer:
    def presign_get(self, bucket: str, key: str, ttl_s: int) -> str:
        return f"https://storage.example.com/{bucket}/{key}?ttl={ttl_s}"


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

    async with runtime.db.transaction(workspace_id=setup.workspace_id) as session:
        call = (await session.execute(select(Call).where(Call.id == call_id))).scalar_one()
    state = calls.recording_state(call, signer=Signer(), bucket="callwright-recordings")
    assert state == {
        "call_id": call_id,
        "recording_enabled": False,
        "recording_setting_source": "agent",
        "recording_status": "not_recorded",
        "recording_url": None,
        "expires_at": None,
    }


async def test_recording_state_for_an_available_recording(runtime: Runtime) -> None:
    setup = await ended_call(runtime)
    owner_sql(
        "update calls set recording_status = 'available', "
        "recording_key = 'recordings/ws/x.mp4' where id = %s",
        (setup.call_id,),
    )
    async with runtime.db.transaction(workspace_id=setup.workspace_id) as session:
        call = (await session.execute(select(Call).where(Call.id == setup.call_id))).scalar_one()
    state = calls.recording_state(call, signer=Signer(), bucket="b")
    assert state["recording_url"] == "https://storage.example.com/b/recordings/ws/x.mp4?ttl=600"
    assert state["expires_at"] is not None
    failed = calls.recording_state(call, signer=None, bucket="b")
    assert failed["recording_url"] is None
