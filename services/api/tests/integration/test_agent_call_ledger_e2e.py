"""Wave 2 end to end: 001 + 002 + 003 on the real API, no fakes between the features.

An agent is built and published through the 002 routes, a test call is started on the
published version through ``POST /v1/sessions/web-call`` (003, resolved by the real
``AgentVersionsAdapter`` over ``agent_versions.service``), the voice worker's own
``InternalApiClient``, ``EventRecorder`` and ``EventPoster`` claim it and stream a two-minute
conversation, the call ends, the post-call steps run, and the call is priced and charged in the
001 ledger: one ``call_charge`` transaction, a stored cost breakdown, and the balance lowered by
exactly that amount.

The only stand-ins are the fake LiveKit (``LIVEKIT_MODE=fake``) and the inline job queue the
``runtime`` fixture installs; the fake agent-versions port it installs is swapped back for the
real adapter.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import httpx
from fastapi import FastAPI

from app.agent_versions.runtime_port import AgentVersionsAdapter
from app.calls import ports
from tests.agent_helpers import create_ok
from tests.conftest import Account
from tests.contract.worker_compat import worker_client, worker_modules
from tests.runtime_support import Runtime, dispatch_metadata, idem, owner_sql


class Clock:
    def __init__(self) -> None:
        self.now = datetime.now(UTC) - timedelta(minutes=10)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


async def _balance(client: httpx.AsyncClient, account: Account) -> Decimal:
    response = await client.get("/v1/billing/balance", headers=account.headers)
    assert response.status_code == 200, response.text
    return Decimal(response.json()["balance_usd"])


async def test_agent_built_published_called_and_charged(
    app: FastAPI, client: httpx.AsyncClient, account: Account, runtime: Runtime
) -> None:
    ports.set_agent_versions(AgentVersionsAdapter())  # the runtime fixture restores its default
    internal_api, metrics = worker_modules()
    worker, contract_hooks, worker_http = worker_client(app)

    # 002: build an agent and publish its first version.
    agent = await create_ok(
        client,
        account,
        name="Front desk",
        config={
            "prompt": "You answer calls for {{company_name}}.",
            "begin_message": "Hi {{customer_name}}, this is {{company_name}}.",
            "dynamic_variables": [
                {"name": "customer_name", "default": "there"},
                {"name": "company_name", "default": "Acme Dental"},
            ],
        },
    )
    version_id = agent["draft_version"]["id"]
    published = await client.put(
        f"/v1/agents/{agent['id']}/published-version",
        json={"version_id": version_id},
        headers=account.headers,
    )
    assert published.status_code == 200, published.text
    balance_before = await _balance(client, account)

    # 003: a test call on the published version.
    session = await client.post(
        "/v1/sessions/web-call",
        json={
            "agent_id": agent["id"],
            "version": "published",
            "dynamic_variables": {"customer_name": "Priya"},
        },
        headers={**account.headers, **idem()},
    )
    assert session.status_code == 201, session.text
    call_id = session.json()["call_id"]
    assert session.json()["agent_version_id"] == version_id
    assert owner_sql("select agent_id, agent_version_id, is_test from calls where id = %s", (call_id,)) == [
        (agent["id"], version_id, True)
    ]

    # The worker claims the call with its own client and gets the frozen 002 config.
    claim = await worker.claim(
        internal_api.ClaimRequest(
            job_id="AJ_e2e",
            room_name=session.json()["room_name"],
            worker_id="AW_e2e",
            dispatch_metadata=dispatch_metadata(runtime, call_id),
        )
    )
    assert claim.admitted and claim.call_id == call_id
    rt: Any = claim.runtime
    assert rt.agent_version_id == version_id
    assert rt.config["prompt"] == "You answer calls for {{company_name}}."
    assert rt.variables["customer_name"] == "Priya" and rt.variables["company_name"] == "Acme Dental"
    assert rt.stt_resolved_model  # Auto resolved through voices.service.resolve_auto_stt
    await runtime.run_jobs("start_recording")

    # Events: greeting, one exchange, usage meters, the caller hangs up after 120 s.
    clock = Clock()
    recorder = metrics.EventRecorder(wall_clock=clock)
    ended: list[str] = []
    poster = metrics.EventPoster(call_id, recorder, worker, on_end_call=ended.append)
    recorder.status("in_progress")
    recorder.turn(metrics.TurnRecord(turn_index=0, e2e_ms=900))
    recorder.message("agent", "Hi Priya, this is Acme Dental.", started_ms=0, ended_ms=1800, turn_index=0)
    clock.advance(60)
    recorder.message("user", "Can I book a cleaning?", started_ms=60_000, ended_ms=62_000, source="voice")
    recorder.turn(
        metrics.TurnRecord(
            turn_index=1, stt_final_ms=150, eou_delay_ms=300, llm_ttft_ms=250, tts_ttfb_ms=120, e2e_ms=820
        )
    )
    recorder.message("agent", "Sure, Tuesday at ten works.", started_ms=62_800, ended_ms=65_000, turn_index=1)
    llm, tts = rt.config["llm"], rt.config["tts"]
    recorder.meters.add_stt(rt.config["stt"]["provider"], rt.stt_resolved_model, 120_000)
    recorder.meters.add_llm(
        llm["provider"], llm["model"], input_tokens=2_400, cached_input_tokens=0, output_tokens=80
    )
    recorder.meters.add_tts(tts["provider"], tts.get("model"), 64)
    first = await poster.flush()
    assert first is not None and first.control.action == "none"
    clock.advance(60)
    recorder.status("ended", disconnect_reason="user_hangup")
    await poster.stop()
    assert ended == []
    assert owner_sql("select status, billable_seconds from calls where id = %s", (call_id,)) == [
        ("ended", 120)
    ]

    # Post-call steps: transcript, price and charge, complete.
    await runtime.run_jobs("run_pipeline")
    call = owner_sql("select status, pipeline_status, cost_total_usd from calls where id = %s", (call_id,))[0]
    assert call[0] == "completed" and call[1] in ("done", "done_with_warnings")
    cost_total: Decimal = call[2]
    assert cost_total > 0

    # 001: one call_charge in the ledger with the stored breakdown; the balance dropped by it.
    cost_row = owner_sql(
        "select c.total_usd, c.billed_seconds, t.amount_usd from call_costs c "
        "join credit_transactions t on t.id = c.txn_id where c.call_id = %s",
        (call_id,),
    )
    assert cost_row == [(cost_total, 120, -cost_total)]
    listing = await client.get("/v1/billing/transactions?type=call_charge", headers=account.headers)
    assert listing.status_code == 200, listing.text
    charges = [t for t in listing.json()["items"] if t["call_id"] == call_id]
    assert len(charges) == 1
    assert Decimal(charges[0]["amount_usd"]) == -cost_total
    breakdown = charges[0]["cost_breakdown"]
    assert breakdown is not None and Decimal(breakdown["total_usd"]) == cost_total
    assert {line["component"] for line in breakdown["lines"]} >= {"stt", "llm", "tts"}
    assert await _balance(client, account) == balance_before - cost_total

    # Running the steps again charges nothing more (idempotent per call).
    await runtime.queue.enqueue("run_pipeline", account.workspace_id, call_id)
    await runtime.run_jobs("run_pipeline")
    assert owner_sql(
        "select count(*) from credit_transactions where call_id = %s and type = 'call_charge'", (call_id,)
    ) == [(1,)]
    assert all(r.status_code == 200 for _, r in contract_hooks.exchanges)
    await worker_http.aclose()
