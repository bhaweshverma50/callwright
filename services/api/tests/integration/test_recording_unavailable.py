"""Recording without an egress service: a missing or broken egress never breaks or blocks a call.

* Egress start fails: the call keeps running, ``recording_status`` is ``failed`` (recording
  unavailable) with the ``recording_unavailable`` processing warning, and the call is still priced
  and completed.
* ``RECORDINGS_ENABLED=false``: admission records every call as ``not_recorded`` (even with the
  agent override ``on``) and the claim schedules no recording start.
"""

from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI

from app.calls import service as calls
from app.calls.jobs import RECORDING_UNAVAILABLE, start_recording_for
from app.core.config import get_settings
from app.core.livekit import EgressTarget
from tests.conftest import Account
from tests.runtime_support import (
    SERVICE_HEADERS,
    Runtime,
    admitted_call,
    agent_config,
    dispatch_metadata,
    ended_call,
    owner_sql,
    start_web_call,
)

BUCKET = "callwright-recordings"


async def test_failed_egress_start_leaves_the_call_running_and_priced(runtime: Runtime) -> None:
    setup = await admitted_call(runtime)
    runtime.livekit.fail_next.add("start_audio_recording")
    assert await start_recording_for(
        runtime.db, runtime.livekit, BUCKET, setup.workspace_id, setup.call_id
    ) == ("failed")
    assert owner_sql(
        "select status, recording_status, egress_id, pipeline_warnings from calls where id = %s",
        (setup.call_id,),
    ) == [("queued", "failed", None, [RECORDING_UNAVAILABLE])]
    # A retried job neither starts a recording nor repeats the warning.
    assert await start_recording_for(
        runtime.db, runtime.livekit, BUCKET, setup.workspace_id, setup.call_id
    ) == ("skipped")

    # The call itself runs and ends normally, then is priced and completed with the warning.
    done = await ended_call(runtime, setup.workspace_id)
    runtime.livekit.fail_next.add("start_audio_recording")
    await start_recording_for(runtime.db, runtime.livekit, BUCKET, done.workspace_id, done.call_id)
    await runtime.run_jobs("run_pipeline")
    row = owner_sql(
        "select status, disconnect_reason, recording_status, pipeline_status, pipeline_warnings, "
        "cost_total_usd > 0 from calls where id = %s",
        (done.call_id,),
    )
    assert row == [
        ("completed", "user_hangup", "failed", "done_with_warnings", [RECORDING_UNAVAILABLE], True)
    ]
    assert owner_sql(
        "select count(*) from credit_transactions where call_id = %s and type = 'call_charge'",
        (done.call_id,),
    ) == [(1,)]


class BrokenEgress:
    """A gateway whose egress raises something other than LiveKitError (bug, network, ...)."""

    async def start_audio_recording(self, room: str, target: EgressTarget) -> str:
        raise RuntimeError("egress service exploded")


async def test_any_egress_error_is_recording_unavailable(runtime: Runtime) -> None:
    setup = await admitted_call(runtime)
    outcome = await start_recording_for(
        runtime.db,
        BrokenEgress(),  # type: ignore[arg-type]
        BUCKET,
        setup.workspace_id,
        setup.call_id,
    )
    assert outcome == "failed"
    assert owner_sql("select recording_status from calls where id = %s", (setup.call_id,)) == [("failed",)]


async def test_recordings_disabled_admits_calls_not_recorded(runtime: Runtime) -> None:
    _, ws = await runtime.workspace()
    agent = runtime.versions.add_agent(ws, agent_config(advanced={"recording": "on"}))
    admission = await calls.admit(
        runtime.db,
        calls.AdmissionRequest(ws, agent.agent_id, "web", "inbound", version="draft", origin="test"),
        catalog=runtime.catalog,
        recordings_enabled=False,
    )
    assert admission.admitted
    assert owner_sql(
        "select recording_enabled, recording_setting_source, recording_status from calls where id = %s",
        (admission.call.id,),
    ) == [(False, "agent", "not_recorded")]


async def test_recordings_enabled_setting_drives_web_calls(
    app: FastAPI,
    client: httpx.AsyncClient,
    account: Account,
    runtime: Runtime,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(get_settings(), "recordings_enabled", False)
    agent = runtime.versions.add_agent(account.workspace_id)
    session = await start_web_call(client, account.headers, agent.agent_id)
    assert session.status_code == 201, session.text
    call_id = session.json()["call_id"]
    claim = await client.post(
        "/v1/internal/calls/claim",
        json={
            "job_id": "AJ_norec",
            "room_name": session.json()["room_name"],
            "worker_id": "AW_norec",
            "dispatch_metadata": dispatch_metadata(runtime, call_id),
        },
        headers=SERVICE_HEADERS,
    )
    assert claim.status_code == 200 and claim.json()["admitted"]
    assert claim.json()["runtime"]["recording_enabled"] is False
    assert "start_recording" not in runtime.queue.names()
    assert owner_sql("select recording_status from calls where id = %s", (call_id,)) == [("not_recorded",)]
