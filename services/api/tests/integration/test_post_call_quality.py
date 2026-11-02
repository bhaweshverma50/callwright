"""Post-call quality end to end (007 T024, T016, T028, T079): a scripted call runs the real 003
pipeline, gets summary, sentiment and variable values, and its enabled checks produce verdicts
with rationales and versions; analysis and judge runs are charged once, free checks never."""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

import httpx
from fastapi import FastAPI

from app.evaluators.registry import builtin_id
from tests.conftest import Account
from tests.fakes.fake_llm import FakeLlm
from tests.quality_support import scripted_call
from tests.runtime_support import Runtime, idem, owner_sql

H = dict[str, str]


async def _variables(client: httpx.AsyncClient, headers: H, agent_id: str) -> None:
    for body in (
        {"name": "appointment_booked", "type": "boolean", "description": "True if a slot was confirmed"},
        {
            "name": "preferred_day",
            "type": "choice",
            "description": "The weekday the caller wants",
            "choices": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"],
        },
    ):
        r = await client.post(f"/v1/agents/{agent_id}/analysis-variables", json=body, headers=headers)
        assert r.status_code == 201, r.text


def _account_runtime(account: Account) -> str:
    return account.workspace_id


async def test_scripted_booking_call_gets_analysis_and_verdicts(
    app: FastAPI, client: httpx.AsyncClient, account: Account, runtime: Runtime, quality: FakeLlm
) -> None:
    h = account.headers
    intent = builtin_id("intent_fulfillment")

    async def prepare(ws: str, agent_id: str) -> None:
        await _variables(client, h, agent_id)
        r = await client.put(
            f"/v1/agents/{agent_id}/eval-settings/{intent}",
            json={"enabled": True, "is_headline": True},
            headers=h,
        )
        assert r.status_code == 200, r.text

    call = await scripted_call(runtime, account.workspace_id, latencies=[800, 3400], prepare=prepare)

    analysis = (await client.get(f"/v1/calls/{call.call_id}/analysis", headers=h)).json()
    assert analysis["status"] == "completed" and analysis["summary"]
    assert analysis["sentiment"] in ("positive", "neutral")
    values = {v["name"]: v["value"] for v in analysis["values"]}
    assert values == {"appointment_booked": True, "preferred_day": "Tuesday"}
    assert analysis["model"] == "azure_openai/gpt-5.1"  # the agent's main model
    # Written onto the call through calls.service.set_analysis (006 list and webhook read it).
    row = owner_sql("select summary, sentiment, analysis from calls where id = %s", (call.call_id,))[0]
    assert row[0] == analysis["summary"] and row[2] == values

    body = (await client.get(f"/v1/calls/{call.call_id}/evaluations", headers=h)).json()
    runs = {r["evaluator_name"]: r for r in body["runs"]}
    assert set(runs) == {"audio_silence", "intent_fulfillment", "latency_slo"}
    assert runs["audio_silence"]["verdict"] == "not_applicable"
    assert runs["audio_silence"]["rationale"] == "Not applicable: no recording"
    latency = runs["latency_slo"]
    assert latency["verdict"] == "fail" and [i["verdict"] for i in latency["items"]] == ["pass", "fail"]
    assert latency["settings_snapshot"] == {"threshold_ms": 3000}
    assert runs["intent_fulfillment"]["verdict"] == "pass" and runs["intent_fulfillment"]["rationale"]
    assert runs["intent_fulfillment"]["judge_model"] == "openai/gpt-5-mini"
    for r in body["runs"]:
        assert r["evaluator_version"] == 1 and r["status"] == "completed"
    assert body["eval_status"] == "failed" and (body["pass_count"], body["fail_count"]) == (1, 1)

    # Charges: one post_call_analysis and one eval.intent_fulfillment; free checks never charge.
    charges = owner_sql(
        "select feature_key, count(*) from usage_events where ref_id = %s and feature_key <> 'calls' "
        "group by feature_key order by 1",
        (call.call_id,),
    )
    assert charges == [("eval.intent_fulfillment", 1), ("post_call_analysis", 1)]

    # 006 list shows the quality summary through the port.
    listing = (await client.get("/v1/calls", params={"call_id": call.call_id}, headers=h)).json()
    assert listing["items"][0]["quality"]["eval_status"] == "failed"

    # Replaying the pipeline changes nothing and charges nothing more.
    await runtime.queue.enqueue("run_pipeline", account.workspace_id, call.call_id)
    await runtime.run_jobs("run_pipeline")
    await runtime.run_jobs("evaluate_call")
    again = owner_sql(
        "select count(*) from usage_events where ref_id = %s and feature_key <> 'calls'", (call.call_id,)
    )
    assert again == [(2,)]


async def test_silent_caller_is_too_short_to_analyse_and_judge(
    client: httpx.AsyncClient, account: Account, runtime: Runtime, quality: FakeLlm
) -> None:
    h = account.headers
    call = await scripted_call(runtime, account.workspace_id, lines=[("agent", "Hello? Is anyone there?")])
    analysis = (await client.get(f"/v1/calls/{call.call_id}/analysis", headers=h)).json()
    assert analysis["status"] == "skipped" and analysis["skip_reason"] == "too_short"
    assert analysis["summary"] is None
    runs = {
        r["evaluator_name"]: r
        for r in (await client.get(f"/v1/calls/{call.call_id}/evaluations", headers=h)).json()["runs"]
    }
    # Intent fulfilment (a paid judge, on by default) is skipped; free checks still run.
    assert runs["intent_fulfillment"]["status"] == "skipped"
    assert runs["intent_fulfillment"]["skip_reason"] == "too_short"
    assert runs["latency_slo"]["status"] == "completed"


async def test_zero_balance_skips_analysis_and_judges(
    client: httpx.AsyncClient, account: Account, runtime: Runtime, quality: FakeLlm
) -> None:
    h = account.headers
    intent = builtin_id("intent_fulfillment")

    async def prepare(ws: str, agent_id: str) -> None:
        await client.put(f"/v1/agents/{agent_id}/eval-settings/{intent}", json={"enabled": True}, headers=h)
        await runtime.set_balance(ws, Decimal("0"))

    call = await scripted_call(runtime, account.workspace_id, prepare=prepare)
    analysis = (await client.get(f"/v1/calls/{call.call_id}/analysis", headers=h)).json()
    assert analysis["status"] == "skipped" and analysis["skip_reason"] == "insufficient_credit"
    runs = {
        r["evaluator_name"]: r
        for r in (await client.get(f"/v1/calls/{call.call_id}/evaluations", headers=h)).json()["runs"]
    }
    assert runs["intent_fulfillment"]["status"] == "skipped"
    assert runs["intent_fulfillment"]["skip_reason"] == "insufficient_credit"
    assert runs["latency_slo"]["status"] == "completed"  # free checks still run
    assert owner_sql(
        "select count(*) from usage_events where ref_id = %s and feature_key like 'eval.%%'", (call.call_id,)
    ) == [(0,)]
    # Re-run after a top-up.
    await runtime.set_balance(account.workspace_id, Decimal("5"))
    r = await client.post(f"/v1/calls/{call.call_id}/analysis/rerun", headers={**h, **idem()})
    assert r.status_code == 202, r.text
    await runtime.run_jobs("rerun_analysis")
    analysis = (await client.get(f"/v1/calls/{call.call_id}/analysis", headers=h)).json()
    assert analysis["status"] == "completed"
    assert owner_sql(
        "select count(*) from usage_events where ref_id = %s and feature_key = 'post_call_analysis'",
        (call.call_id,),
    ) == [(1,)]


async def test_sampling_skips_unsampled_live_calls_without_charge_and_rerun_judges(
    client: httpx.AsyncClient, account: Account, runtime: Runtime, quality: FakeLlm
) -> None:
    from app.evals.sampling import selected

    h = account.headers
    intent = builtin_id("intent_fulfillment")

    async def prepare(ws: str, agent_id: str) -> None:
        r = await client.put(
            f"/v1/agents/{agent_id}/eval-settings/{intent}",
            json={"enabled": True, "overrides": {"sample_rate_pct": 1}},
            headers=h,
        )
        assert r.status_code == 200, r.text

    call = None
    for _ in range(5):  # a 1% rate leaves (almost) every call out; find one that is
        candidate = await scripted_call(runtime, account.workspace_id, prepare=prepare)
        if not selected(candidate.call_id, "intent_fulfillment", 1):
            call = candidate
            break
    assert call is not None
    runs = {
        r["evaluator_name"]: r
        for r in (await client.get(f"/v1/calls/{call.call_id}/evaluations", headers=h)).json()["runs"]
    }
    assert (
        runs["intent_fulfillment"]["status"] == "skipped"
        and runs["intent_fulfillment"]["skip_reason"] == "not_sampled"
    )
    assert owner_sql(
        "select count(*) from usage_events where ref_id = %s and feature_key like 'eval.%%'", (call.call_id,)
    ) == [(0,)]
    r = await client.post(f"/v1/calls/{call.call_id}/evaluations/rerun", headers={**h, **idem()})
    assert r.status_code == 202, r.text
    await runtime.run_jobs("evaluate_call")
    body = (await client.get(f"/v1/calls/{call.call_id}/evaluations?include_history=true", headers=h)).json()
    runs = {r["evaluator_name"]: r for r in body["runs"]}
    assert (
        runs["intent_fulfillment"]["status"] == "completed"
        and runs["intent_fulfillment"]["trigger"] == "rerun"
    )
    assert any(x["skip_reason"] == "not_sampled" for x in body["history"])


async def test_judge_error_is_retried_once_then_error(
    client: httpx.AsyncClient, account: Account, runtime: Runtime, quality: FakeLlm
) -> None:
    h = account.headers
    intent = builtin_id("intent_fulfillment")
    attempts: list[int] = []
    original = quality.responder

    def flaky(system: str, user: str, purpose: str | None) -> str:
        if purpose == "eval_judge":
            attempts.append(1)
            return "[error]"
        assert original is not None
        return original(system, user, purpose)

    quality.responder = flaky

    async def prepare(ws: str, agent_id: str) -> None:
        await client.put(f"/v1/agents/{agent_id}/eval-settings/{intent}", json={"enabled": True}, headers=h)

    call = await scripted_call(runtime, account.workspace_id, prepare=prepare)
    runs = {
        r["evaluator_name"]: r
        for r in (await client.get(f"/v1/calls/{call.call_id}/evaluations", headers=h)).json()["runs"]
    }
    assert runs["intent_fulfillment"]["status"] == "error" and runs["intent_fulfillment"]["error"]
    assert len(attempts) == 2  # first attempt and one automatic retry
    assert owner_sql(
        "select attempt from evaluator_runs where call_id = %s and evaluator_id = %s", (call.call_id, intent)
    ) == [(2,)]


def _load(text: str) -> Any:
    return json.loads(text)
