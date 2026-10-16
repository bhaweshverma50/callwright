"""Browser test call end to end on the API side (003 T028, US1 independent test, US4).

Web call request, worker claim, three scripted turns, caller leaves: the call is ``ended`` with
``user_hangup`` and one ``turn`` row per agent reply; the pipeline then prices it once and
marks it ``completed``.
"""

from __future__ import annotations

from decimal import Decimal

import httpx
from fastapi import FastAPI

from tests.conftest import Account
from tests.runtime_support import (
    SERVICE_HEADERS,
    Events,
    Runtime,
    dispatch_metadata,
    owner_sql,
    start_web_call,
)


async def test_web_call_flow(
    app: FastAPI, client: httpx.AsyncClient, account: Account, runtime: Runtime
) -> None:
    agent = runtime.versions.add_agent(account.workspace_id)
    session = await start_web_call(
        client, account.headers, agent.agent_id, dynamic_variables={"customer_name": "Priya"}
    )
    assert session.status_code == 201, session.text
    call_id = session.json()["call_id"]

    claim = await client.post(
        "/v1/internal/calls/claim",
        json={
            "job_id": "AJ_flow",
            "room_name": session.json()["room_name"],
            "worker_id": "AW_flow",
            "dispatch_metadata": dispatch_metadata(runtime, call_id),
        },
        headers=SERVICE_HEADERS,
    )
    assert claim.status_code == 200 and claim.json()["admitted"]
    assert claim.json()["runtime"]["variables"]["customer_name"] == "Priya"
    await runtime.run_jobs("start_recording")
    assert owner_sql(
        "select recording_status, egress_id is not null from calls where id = %s", (call_id,)
    ) == [("recording", True)]

    ev = Events()
    first = [ev.status("in_progress"), ev.turn(0, e2e_ms=950), ev.message("agent", "Hi Priya")]
    for i in (1, 2, 3):
        ev.advance(3)
        first += [ev.message("user", f"q{i}"), ev.turn(i, e2e_ms=700 + 10 * i), ev.message("agent", f"a{i}")]
    first.append(ev.usage(audio_ms=10_000, input_tokens=900, output_tokens=60, chars=120))
    response = await client.post(
        f"/v1/internal/calls/{call_id}/events", json={"events": first}, headers=SERVICE_HEADERS
    )
    assert response.status_code == 200
    assert response.json() == {"accepted": len(first), "duplicates": 0, "control": {"action": "none"}}
    assert owner_sql("select status from calls where id = %s", (call_id,)) == [("in_progress",)]
    assert "call_started" not in [j.name for j in runtime.queue.jobs]  # no webhook URL configured

    ev.advance(1.2)
    last = [ev.status("ended", disconnect_reason="user_hangup"), ev.usage(audio_ms=11_000, chars=130)]
    assert (
        await client.post(
            f"/v1/internal/calls/{call_id}/events", json={"events": last}, headers=SERVICE_HEADERS
        )
    ).status_code == 200

    row = owner_sql(
        "select channel, status, disconnect_reason, billable_seconds, usage_seq, is_test "
        "from calls where id = %s",
        (call_id,),
    )
    assert row == [("web", "ended", "user_hangup", 11, ev.seq, True)]
    turns = owner_sql(
        "select turn_index from call_events where call_id = %s and type = 'turn' order by seq", (call_id,)
    )
    assert [t[0] for t in turns] == [0, 1, 2, 3]

    await runtime.run_jobs("run_pipeline")
    final = owner_sql(
        "select status, pipeline_status, cost_total_usd, latency_stats->>'e2e_p50_ms', "
        "jsonb_array_length(transcript->'items') from calls where id = %s",
        (call_id,),
    )
    assert final[0][0] == "completed" and final[0][1] == "done"
    assert final[0][2] > Decimal(0) and final[0][3] == "720" and final[0][4] == 7
    assert owner_sql(
        "select count(*) from credit_transactions where call_id = %s and type = 'call_charge'", (call_id,)
    ) == [(1,)]
    steps = owner_sql(
        "select step, status from call_pipeline_steps where call_id = %s order by step", (call_id,)
    )
    assert dict(steps) == {
        "analyze": "skipped",
        "complete": "done",
        "evaluate": "skipped",
        "finalize_transcript": "done",
        "notify_analyzed": "skipped",
        "price_and_charge": "done",
    }


async def test_caller_never_connects_is_failed_and_not_billed(
    app: FastAPI, client: httpx.AsyncClient, account: Account, runtime: Runtime
) -> None:
    agent = runtime.versions.add_agent(account.workspace_id)
    session = await start_web_call(client, account.headers, agent.agent_id)
    call_id = session.json()["call_id"]
    ev = Events()
    events = [ev.status("failed", disconnect_reason="error", diagnostic="caller_never_joined")]
    response = await client.post(
        f"/v1/internal/calls/{call_id}/events", json={"events": events}, headers=SERVICE_HEADERS
    )
    assert response.status_code == 200
    assert owner_sql("select status, diagnostic, billable_seconds from calls where id = %s", (call_id,)) == [
        ("failed", "caller_never_joined", 0)
    ]
    assert "run_pipeline" not in runtime.queue.names()
    closed = await client.post(
        f"/v1/internal/calls/{call_id}/events", json={"events": []}, headers=SERVICE_HEADERS
    )
    assert closed.status_code == 409
