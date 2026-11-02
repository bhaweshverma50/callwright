"""Contract tests for eval settings, evaluations, reruns and verdict diffs (007 T025, T026)."""

from __future__ import annotations

import httpx

from app.evaluators.registry import builtin_id
from tests.conftest import Account
from tests.contract.conftest import check
from tests.fakes.fake_llm import FakeLlm
from tests.quality_support import scripted_call
from tests.runtime_support import Runtime, agent_config, idem

INTENT = builtin_id("intent_fulfillment")
FACTUAL = builtin_id("factual_consistency")


async def test_settings_listing_per_agent_type(
    client: httpx.AsyncClient, account: Account, runtime: Runtime
) -> None:
    h = account.headers
    single = runtime.versions.add_agent(account.workspace_id).agent_id
    items = check(await client.get(f"/v1/agents/{single}/eval-settings", headers=h)).json()["items"]
    assert len(items) == 8
    default_on = {"audio_silence", "latency_slo", "intent_fulfillment"}
    assert {i["name"] for i in items if i["enabled"]} == default_on
    assert [i["display_name"] for i in items] == sorted(i["display_name"] for i in items)
    judges = [i for i in items if i["cost_class"] == "llm_judge"]
    assert judges and all(i["est_cost_per_call_usd"] > 0 for i in judges)
    # Intent fulfilment is the one judge on by default; every other paid check starts off.
    assert all(not i["enabled"] for i in judges if i["name"] != "intent_fulfillment")
    flow = runtime.versions.add_agent(
        account.workspace_id, agent_config(type="flow"), agent_type="flow"
    ).agent_id
    flow_items = check(await client.get(f"/v1/agents/{flow}/eval-settings", headers=h)).json()["items"]
    assert len(flow_items) == 12
    assert {i["name"] for i in flow_items if i["enabled"]} == {
        "audio_silence",
        "flow_completion",
        "intent_fulfillment",
        "latency_slo",
        "node_dead_end",
        "stuck_loop_detector",
    }


async def test_put_validation_full_replace_and_headline_limit(
    client: httpx.AsyncClient, account: Account, runtime: Runtime
) -> None:
    h = account.headers
    agent = runtime.versions.add_agent(
        account.workspace_id, agent_config(type="flow"), agent_type="flow"
    ).agent_id
    url = f"/v1/agents/{agent}/eval-settings"
    bad = check(
        await client.put(
            f"{url}/{INTENT}", json={"enabled": True, "overrides": {"sample_rate_pct": 150}}, headers=h
        )
    )
    assert bad.status_code == 422
    assert bad.json()["errors"] == [
        {
            "pointer": "/overrides/sample_rate_pct",
            "code": "out_of_range",
            "message": "Enter a whole number from 1 to 100",
        }
    ]
    ok = check(
        await client.put(
            f"{url}/{INTENT}",
            json={"enabled": True, "overrides": {"sample_rate_pct": 20}, "is_headline": True},
            headers=h,
        )
    )
    assert ok.status_code == 200
    s = ok.json()
    assert (
        s["effective_settings"]["sample_rate_pct"] == 20
        and s["is_overridden"]
        and s["headline_position"] == 1
    )
    # Full replacement: a save without overrides clears them.
    cleared = check(
        await client.put(f"{url}/{INTENT}", json={"enabled": False, "is_headline": True}, headers=h)
    ).json()
    assert (
        cleared["overrides"] == {}
        and cleared["effective_settings"]["sample_rate_pct"] == 100
        and not cleared["enabled"]
    )
    for name in ("latency_slo", "audio_silence", "stuck_loop_detector"):
        r = check(
            await client.put(
                f"{url}/{builtin_id(name)}", json={"enabled": True, "is_headline": True}, headers=h
            )
        )
        assert r.status_code == 200
    fifth = check(
        await client.put(
            f"{url}/{builtin_id('node_dead_end')}", json={"enabled": True, "is_headline": True}, headers=h
        )
    )
    assert fifth.status_code == 409 and fifth.json()["detail"] == "Up to 4 headline checks per agent"
    single = runtime.versions.add_agent(account.workspace_id).agent_id
    wrong_type = check(
        await client.put(
            f"/v1/agents/{single}/eval-settings/{builtin_id('flow_completion')}",
            json={"enabled": True},
            headers=h,
        )
    )
    assert wrong_type.status_code == 422
    unknown = check(
        await client.put(f"{url}/evl_01ARZ3NDEKTSV4RRFFQ69G5FAV", json={"enabled": True}, headers=h)
    )
    assert unknown.status_code == 404


async def test_evaluations_rerun_and_verdict_diff(
    client: httpx.AsyncClient, account: Account, runtime: Runtime, quality: FakeLlm
) -> None:
    h = account.headers
    a = await scripted_call(runtime, account.workspace_id, latencies=[700, 900])
    b = await scripted_call(runtime, account.workspace_id, latencies=[700, 3900])
    got = check(
        await client.get(f"/v1/calls/{a.call_id}/evaluations", params={"include_history": "true"}, headers=h)
    )
    assert got.json()["eval_status"] == "passed" and got.json()["history"] == []
    rerun = check(await client.post(f"/v1/calls/{a.call_id}/evaluations/rerun", headers={**h, **idem()}))
    assert rerun.status_code == 202 and {r["status"] for r in rerun.json()["runs"]} == {"pending"}
    busy = check(await client.post(f"/v1/calls/{a.call_id}/evaluations/rerun", headers={**h, **idem()}))
    assert busy.status_code == 409 and busy.json()["detail"] == "Checks are already running"
    running = check(await client.get(f"/v1/calls/{a.call_id}/evaluations", headers=h)).json()
    assert running["eval_status"] == "running"
    await runtime.run_jobs("evaluate_call")
    done = check(
        await client.get(f"/v1/calls/{a.call_id}/evaluations", params={"include_history": "true"}, headers=h)
    ).json()
    # The rerun supersedes the three default checks: long silences, turn latency, intent fulfilment.
    assert done["eval_status"] == "passed" and len(done["history"]) == 3
    assert all(r["superseded_at"] for r in done["history"]) and all(
        r["trigger"] == "rerun" for r in done["runs"]
    )
    subset = check(
        await client.post(
            f"/v1/calls/{a.call_id}/evaluations/rerun",
            json={"evaluator_ids": [FACTUAL]},
            headers={**h, **idem()},
        )
    )
    assert subset.status_code == 422  # not switched on for this agent
    diff = check(
        await client.get(
            "/v1/evals/verdict-diff",
            params={"base_call_id": a.call_id, "other_call_id": b.call_id},
            headers=h,
        )
    )
    rows = {r["evaluator_name"]: r for r in diff.json()["items"]}
    assert (
        rows["latency_slo"]["base"]["verdict"] == "pass" and rows["latency_slo"]["other"]["verdict"] == "fail"
    )
    assert rows["latency_slo"]["score_delta"] > 0 and rows["latency_slo"]["other_rationale"]
    missing = check(
        await client.get(
            "/v1/evals/verdict-diff",
            params={"base_call_id": a.call_id, "other_call_id": "call_01ARZ3NDEKTSV4RRFFQ69G5FAV"},
            headers=h,
        )
    )
    assert missing.status_code == 404
    # 006 compare view reads the same diffs through the port.
    compare = await client.get("/v1/calls/compare", params={"left": a.call_id, "right": b.call_id}, headers=h)
    if compare.status_code == 200:
        assert any(d["evaluator_name"] == "latency_slo" for d in compare.json().get("verdict_diffs", []))
