"""Calibration on seeded labels (007 T050; US4 scenarios 1 to 5): matrix, agreement, reading,
conflicting labels, simulated calls and other workspaces excluded, version scope."""

from __future__ import annotations

import httpx
import pytest

from app.evaluators.registry import builtin_id
from tests.conftest import Account, signup
from tests.contract.conftest import check
from tests.quality_support import seed_agent, seed_call, seed_label, seed_run, user_id


def seed_calibration(ws: str, me: str) -> tuple[str, str]:
    """10 labelled calls for intent_fulfillment: 4 both pass, 2 both fail, 2 over-eager, 2 missed."""
    agent = seed_agent(ws)
    plan = [("pass", "good")] * 4 + [("fail", "bad")] * 2 + [("fail", "good")] * 2 + [("pass", "bad")] * 2
    for verdict, label in plan:
        call = seed_call(ws, agent)
        seed_run(ws, call, agent[0], "intent_fulfillment", verdict, score=0.9 if verdict == "pass" else 0.2)
        seed_run(ws, call, agent[0], "latency_slo", "pass")
        seed_label(ws, call, me, label)
    return agent


async def test_seeded_matrix_and_reading(client: httpx.AsyncClient, account: Account) -> None:
    h = account.headers
    agent = seed_calibration(account.workspace_id, account.user_id)
    # Conflicting labels: excluded and counted.
    tie = seed_call(account.workspace_id, agent)
    seed_run(account.workspace_id, tie, agent[0], "intent_fulfillment", "pass")
    seed_label(account.workspace_id, tie, account.user_id, "good")
    seed_label(account.workspace_id, tie, user_id(), "bad")
    # Simulated calls never count.
    sim = seed_call(account.workspace_id, agent, origin="simulation")
    seed_run(account.workspace_id, sim, agent[0], "intent_fulfillment", "fail")
    seed_label(account.workspace_id, sim, account.user_id, "good")
    # A labelled call with no evaluator results counts as labelled only.
    seed_label(account.workspace_id, seed_call(account.workspace_id, agent), account.user_id, "good")
    # Another workspace's data is invisible.
    other = await signup(client, client._transport.app)  # type: ignore[attr-defined]
    seed_calibration(other.workspace_id, other.user_id)

    rows = check(await client.get("/v1/calibration/evaluators", headers=h)).json()["items"]
    intent = next(r for r in rows if r["evaluator_name"] == "intent_fulfillment")
    assert (
        intent["both_pass"],
        intent["both_fail"],
        intent["over_eager"],
        intent["missed"],
        intent["n"],
    ) == (4, 2, 2, 2, 10)
    assert intent["agreement_rate"] == pytest.approx(0.6) and intent["reading"] == "partial"
    assert intent["agreement_ci"]["low"] == pytest.approx(0.313, abs=0.001)
    assert intent["under_min_sample"] is False and intent["evaluator_version"] == 1
    latency = next(r for r in rows if r["evaluator_name"] == "latency_slo")
    assert (latency["both_pass"], latency["missed"], latency["reading"]) == (6, 4, "misses")
    summary = check(await client.get("/v1/calibration/summary", headers=h)).json()
    assert summary == {
        "annotated_calls": 12,
        "annotated_and_evaluated_calls": 10,
        "conflicting_label_calls": 1,
        "min_sample_for_signal": 5,
    }
    scoped = check(
        await client.get("/v1/calibration/summary", params={"agent_id": agent[0]}, headers=h)
    ).json()
    assert scoped["annotated_calls"] == 12


async def test_under_minimum_threshold_hint_and_versions(client: httpx.AsyncClient, account: Account) -> None:
    h = account.headers
    ws = account.workspace_id
    agent = seed_agent(ws)
    for verdict, label in [("pass", "good")] * 3 + [("fail", "bad")]:
        call = seed_call(ws, agent)
        seed_run(ws, call, agent[0], "tool_call_correctness", verdict)
        seed_label(ws, call, account.user_id, label)
    # Anomaly scores (higher is worse): good calls near, bad calls far.
    for score, label in [
        (0.2, "good"),
        (0.3, "good"),
        (0.35, "good"),
        (0.8, "bad"),
        (0.9, "bad"),
        (0.75, "good"),
    ]:
        call = seed_call(ws, agent)
        seed_run(ws, call, agent[0], "anomaly_detection", "fail" if score > 0.7 else "pass", score=score)
        seed_label(ws, call, account.user_id, label)
    # A run of an older version only counts with version_scope=all.
    from tests.runtime_support import owner_sql

    owner_sql(
        "insert into evaluator_versions (evaluator_id, version, definition) values (%s, 0 + 1, '{}'::jsonb) "
        "on conflict do nothing",
        (builtin_id("factual_consistency"),),
    )
    call = seed_call(ws, agent)
    seed_label(ws, call, account.user_id, "good")
    owner_sql("update evaluators set current_version = 2 where id = %s", (builtin_id("factual_consistency"),))
    owner_sql(
        (
            "insert into evaluator_versions (evaluator_id, version, definition) values (%s, 2, "
            "'{}'::jsonb) on conflict do nothing"
        ),
        (builtin_id("factual_consistency"),),
    )
    try:
        seed_run(ws, call, agent[0], "factual_consistency", "pass", version=1)
        rows = {
            r["evaluator_name"]: r
            for r in check(await client.get("/v1/calibration/evaluators", headers=h)).json()["items"]
        }
        tools = rows["tool_call_correctness"]
        assert tools["n"] == 4 and tools["under_min_sample"] and tools["reading"] == "insufficient"
        anomaly = rows["anomaly_detection"]
        assert anomaly["current_threshold"] == 0.7 and anomaly["n"] == 6
        assert anomaly["best_threshold"] == pytest.approx(0.75) and anomaly["best_threshold_agreement"] == 1.0
        assert "factual_consistency" not in rows
        all_versions = check(
            await client.get("/v1/calibration/evaluators", params={"version_scope": "all"}, headers=h)
        ).json()["items"]
        fc = next(r for r in all_versions if r["evaluator_name"] == "factual_consistency")
        assert fc["n"] == 1 and fc["version_scope"] == "all" and fc["evaluator_version"] is None
    finally:
        owner_sql(
            "update evaluators set current_version = 1 where id = %s", (builtin_id("factual_consistency"),)
        )


async def test_rows_split_by_flow_node(client: httpx.AsyncClient, account: Account) -> None:
    h = account.headers
    ws = account.workspace_id
    agent = seed_agent(ws, "flow")
    for verdict, label, node_verdict in [("fail", "bad", "fail")] * 3 + [("pass", "good", "pass")] * 2:
        call = seed_call(ws, agent)
        seed_run(
            ws,
            call,
            agent[0],
            "node_dead_end",
            verdict,
            items=[
                {"node": "greet", "label": "Greeting", "verdict": "pass"},
                {"node": "book", "label": "Book slot", "verdict": node_verdict},
            ],
        )
        seed_label(ws, call, account.user_id, label)
    rows = [
        r
        for r in check(await client.get("/v1/calibration/evaluators", headers=h)).json()["items"]
        if r["evaluator_name"] == "node_dead_end"
    ]
    by_node = {r["flow_node_id"]: r for r in rows}
    assert set(by_node) == {None, "greet", "book"}
    assert by_node["book"]["reading"] == "strong" and by_node["book"]["flow_node_label"] == "Book slot"
    assert (by_node["greet"]["both_pass"], by_node["greet"]["missed"]) == (2, 3)
