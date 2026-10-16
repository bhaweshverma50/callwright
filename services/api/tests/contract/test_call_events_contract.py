"""POST /v1/internal/calls/{call_id}/events against contracts/call_events.yaml (003 T023).

The events are produced by the worker's own ``EventRecorder`` and posted by its ``EventPoster``
and ``InternalApiClient``; every request and response is validated against the contract.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from tests.conftest import Account
from tests.contract.conftest import check
from tests.contract.worker_compat import worker_client, worker_modules
from tests.runtime_support import SERVICE_HEADERS, Runtime, dispatch_metadata, owner_sql, start_web_call


async def _claimed_call(
    app: FastAPI, client: httpx.AsyncClient, account: Account, runtime: Runtime, api: Any
) -> str:
    internal_api, _ = worker_modules()
    agent = runtime.versions.add_agent(account.workspace_id)
    response = await start_web_call(client, account.headers, agent.agent_id)
    assert response.status_code == 201, response.text
    call_id = str(response.json()["call_id"])
    await api.claim(
        internal_api.ClaimRequest(
            job_id=f"AJ_{call_id[-6:]}",
            room_name=response.json()["room_name"],
            worker_id="AW",
            dispatch_metadata=dispatch_metadata(runtime, call_id),
        )
    )
    return call_id


def _full_call(metrics: Any, recorder: Any) -> None:
    """Every event type the worker emits, in the order a short call produces them."""
    recorder.status("in_progress")
    recorder.connected()
    recorder.turn(metrics.TurnRecord(turn_index=0, e2e_ms=850))
    recorder.message("agent", "Hi Priya, thanks for calling.", started_ms=0, ended_ms=1800, turn_index=0)
    recorder.message(
        "user", "What are your hours?", started_ms=2500, ended_ms=4000, confidence=0.93, source="voice"
    )
    recorder.turn(
        metrics.TurnRecord(
            turn_index=1, stt_final_ms=140, eou_delay_ms=320, llm_ttft_ms=260, tts_ttfb_ms=110, e2e_ms=760
        )
    )
    recorder.message(
        "agent", "We open at nine.", started_ms=4800, ended_ms=6000, turn_index=1, interrupted=False
    )
    recorder.tool_call("lookup_hours", ref="t1", arguments={"day": "mon"}, output="9-5", duration_ms=45)
    recorder.flow_transition("n_2", "n_1", "hours asked")
    recorder.dtmf("1234", "received", "termination_key")
    recorder.system("silence_timeout", "no speech")
    recorder.warning("background_audio_unavailable", component="runtime", detail="missing file")
    recorder.warning("vendor_retry", component="stt", provider="deepgram", level="error")
    recorder.meters.add_stt("deepgram", "nova-3", 6000)
    recorder.meters.add_llm(
        "azure_openai", "gpt-5.1", input_tokens=1200, cached_input_tokens=800, output_tokens=40
    )
    recorder.meters.add_tts("elevenlabs", "eleven_flash_v2_5", 48)
    recorder.meters.set_nc("sanas", "vi", 6000)


async def test_worker_event_stream_round_trip(
    app: FastAPI, client: httpx.AsyncClient, account: Account, runtime: Runtime
) -> None:
    _, metrics = worker_modules()
    api, contract_hooks, http = worker_client(app)
    call_id = await _claimed_call(app, client, account, runtime, api)
    ended: list[str] = []
    recorder = metrics.EventRecorder()
    poster = metrics.EventPoster(call_id, recorder, api, on_end_call=ended.append)

    _full_call(metrics, recorder)
    result = await poster.flush()
    assert result is not None and result.duplicates == 0 and result.accepted == recorder.seq
    assert result.control.action == "none" and ended == []

    # A retried batch is accepted as duplicates and changes nothing (idempotent per seq).
    replay = await api.post_events(call_id, recorder.history[:5])
    assert (replay.accepted, replay.duplicates) == (0, 5)

    # An empty batch is a pure heartbeat.
    heartbeat = await api.post_events(call_id, [])
    assert (heartbeat.accepted, heartbeat.duplicates) == (0, 0)

    recorder.status("ended", disconnect_reason="user_hangup")
    await poster.stop()  # final flush appends the usage snapshot after the status
    rows = owner_sql(
        "select status, disconnect_reason, usage_seq = %s, usage->'stt'->0->>'model', "
        "billable_seconds is not null from calls where id = %s",
        (recorder.seq, call_id),
    )
    assert rows == [("ended", "user_hangup", True, "nova-3", True)]
    turns = owner_sql(
        "select turn_index, e2e_ms from call_events where call_id = %s and type = 'turn' order by seq",
        (call_id,),
    )
    assert turns == [(0, 850), (1, 760)]
    assert "run_pipeline" in runtime.queue.names()

    # Once processing starts the call is closed: 409 and the worker stops posting.
    await runtime.run_jobs("run_pipeline")
    recorder.warning("late", component="runtime")
    await poster.flush()
    assert poster.closed
    statuses = [r.status_code for _, r in contract_hooks.exchanges]
    assert statuses[-1] == 409 and set(statuses) <= {200, 409}
    await http.aclose()


async def test_credit_guard_orders_end_call(
    app: FastAPI, client: httpx.AsyncClient, account: Account, runtime: Runtime
) -> None:
    _, metrics = worker_modules()
    api, _, http = worker_client(app)
    call_id = await _claimed_call(app, client, account, runtime, api)
    ended: list[str] = []
    recorder = metrics.EventRecorder()
    poster = metrics.EventPoster(call_id, recorder, api, on_end_call=ended.append)
    recorder.status("in_progress")
    assert (await poster.flush()).control.action == "none"  # type: ignore[union-attr]
    # Balance $0.10 with $0.50 grace: a running cost above $0.60 ends the call.
    await runtime.set_balance(account.workspace_id, Decimal("0.10"))
    owner_sql("update calls set connected_at = now() - interval '6 minutes' where id = %s", (call_id,))
    result = await poster.flush()
    assert result is not None and result.control.action == "end_call"
    assert result.control.disconnect_reason == "insufficient_credit"
    assert ended == ["insufficient_credit"]
    await http.aclose()


@pytest.mark.parametrize(
    "event",
    [
        {"seq": 0, "type": "status", "occurred_at": "2026-10-16T10:00:00Z", "status": "ended"},
        {"seq": 1, "type": "status", "occurred_at": "2026-10-16T10:00:00Z", "status": "teleported"},
        {"seq": 1, "type": "nonsense", "occurred_at": "2026-10-16T10:00:00Z"},
        {
            "seq": 1,
            "type": "dtmf",
            "occurred_at": "2026-10-16T10:00:00Z",
            "digits": "12a",
            "direction": "received",
        },
    ],
)
async def test_invalid_events_are_422(
    app: FastAPI, client: httpx.AsyncClient, account: Account, runtime: Runtime, event: dict[str, Any]
) -> None:
    api, _, http = worker_client(app)
    call_id = await _claimed_call(app, client, account, runtime, api)
    response = check(
        await client.post(
            f"/v1/internal/calls/{call_id}/events", json={"events": [event]}, headers=SERVICE_HEADERS
        )
    )
    assert response.status_code == 422
    await http.aclose()


async def test_unknown_call_and_missing_token(client: httpx.AsyncClient, runtime: Runtime) -> None:
    unknown = check(
        await client.post(
            "/v1/internal/calls/call_01ARZ3NDEKTSV4RRFFQ69G5FAV/events",
            json={"events": []},
            headers=SERVICE_HEADERS,
        )
    )
    assert unknown.status_code == 404
    anonymous = check(
        await client.post("/v1/internal/calls/call_01ARZ3NDEKTSV4RRFFQ69G5FAV/events", json={"events": []})
    )
    assert anonymous.status_code == 401
