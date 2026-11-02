"""Fix revisions and validation with stubbed 008 batches (009 T027, T036; US2, US3)."""

from __future__ import annotations

import uuid
from typing import Any

import psycopg
import pytest

from app.issues.charges import draft_key
from tests.conftest import TEST_DB, _sync_dsn
from tests.issues_support import (
    FACT,
    TOOLS,
    IssueEnv,
    complete_batch,
    ready_issue,
    verdict_plan,
)
from tests.runtime_support import owner_sql
from tests.sim_support import PROMPT

GUIDED = "Keep the greeting unchanged."


async def draft(env: IssueEnv, issue_id: str, **body: Any) -> dict[str, Any]:
    response = await env.post(f"/issues/{issue_id}/fixes", {"mode": "ai", **body})
    assert response.status_code == 201, response.text
    result: dict[str, Any] = response.json()
    return result


async def start_validation(env: IssueEnv, issue_id: str, **body: Any) -> dict[str, Any]:
    response = await env.post(f"/issues/{issue_id}/validate", body)
    assert response.status_code == 202, response.text
    result: dict[str, Any] = response.json()
    return result


async def finish(
    env: IssueEnv,
    attempt: dict[str, Any],
    control_passes: int,
    treatment_passes: int,
    *,
    guard_treatment: str = "pass",
    tools: tuple[str, str] | None = None,
    failed: tuple[str, ...] = (),
) -> dict[str, Any]:
    affected, guard = attempt["affected_call_ids"], attempt["guard_call_ids"]
    extra = {TOOLS: tools[0]} if tools else None
    control = verdict_plan(affected, control_passes, extra=extra)
    control.update({g: {FACT: "pass", **({TOOLS: "pass"} if tools else {})} for g in guard})
    treatment = verdict_plan(affected, treatment_passes, extra={TOOLS: tools[1]} if tools else None)
    treatment.update({g: {FACT: guard_treatment, **({TOOLS: "pass"} if tools else {})} for g in guard})
    complete_batch(env, attempt["control_experiment_id"], control)
    complete_batch(env, attempt["treatment_experiment_id"], treatment, failed=failed)
    await env.queue.enqueue("finalize_validation", env.ws, attempt["treatment_experiment_id"])
    await env.run_jobs("finalize_validation")
    [latest, *_] = (
        await env.client.get(f"/v1/issues/{attempt_issue(env)}/validations", headers=env.headers)
    ).json()["items"]
    return latest


def attempt_issue(env: IssueEnv) -> str:
    return env.calls["issue"][0]


async def setup(env: IssueEnv, *, failing: int = 10, guard: int = 5) -> str:
    issue = await ready_issue(env, failing)
    env.calls["issue"] = [issue["issue_id"]]
    if guard:
        env.seed_calls(guard, verdict="pass", reason="Prices match.", tag="guard", ago_hours=0.5)
    return str(issue["issue_id"])


def usage_rows(key: str) -> int:
    return int(owner_sql("select count(*) from usage_events where idempotency_key = %s", (key,))[0][0])


# US2 --------------------------------------------------------------------------------------------


async def test_ai_draft_picks_allowed_kind_and_charges_once_on_retry(issue_env: IssueEnv) -> None:
    env = issue_env
    issue_id = await setup(env, guard=0)
    key = f"fix-{uuid.uuid4().hex}"
    headers = {**env.headers, "Idempotency-Key": key}
    first = await env.client.post(f"/v1/issues/{issue_id}/fixes", json={"mode": "ai"}, headers=headers)
    again = await env.client.post(f"/v1/issues/{issue_id}/fixes", json={"mode": "ai"}, headers=headers)
    assert first.status_code == again.status_code == 201
    assert first.json() == again.json()
    fix = first.json()
    assert fix["kind"] == "prompt_edit" and fix["source"] == "ai" and fix["revision"] == 1
    assert fix["status"] == "draft" and fix["is_current"]
    assert fix["payload"]["current_prompt"] == PROMPT
    assert fix["rationale"]
    assert fix["diff"][0]["path"] == "/prompt"
    assert fix["variant_config_hash"] and fix["variant_config_hash"] != fix["base_config_hash"]
    assert usage_rows(draft_key(issue_id, 1)) == 1
    listed = (await env.client.get(f"/v1/issues/{issue_id}/fixes", headers=env.headers)).json()["items"]
    assert [f["revision"] for f in listed] == [1]


async def test_kind_guidance_manual_edit_and_revisions(issue_env: IssueEnv) -> None:
    env = issue_env
    issue_id = await setup(env, guard=0)
    await draft(env, issue_id)
    guardrail = await draft(env, issue_id, kind="add_guardrail", guidance=GUIDED)
    assert guardrail["kind"] == "add_guardrail" and guardrail["guidance"] == GUIDED
    edited = await env.post(
        f"/issues/{issue_id}/fixes",
        {
            "mode": "manual",
            "kind": "add_guardrail",
            "payload": {"placement": "agent_prompt", "rule_text": "Quote only prices from the price list."},
        },
        key=False,
    )
    assert edited.status_code == 201, edited.text
    assert edited.json()["source"] == "manual" and edited.json()["revision"] == 3
    listed = (await env.client.get(f"/v1/issues/{issue_id}/fixes", headers=env.headers)).json()["items"]
    assert [(f["revision"], f["status"], f["is_current"]) for f in listed] == [
        (3, "draft", True),
        (2, "superseded", False),
        (1, "superseded", False),
    ]
    detail = await env.issue(issue_id)
    assert detail["current_fix"]["revision"] == 3 and detail["current_fix_kind"] == "add_guardrail"


async def test_kind_not_allowed_and_stale_manual_edit(issue_env: IssueEnv) -> None:
    env = issue_env
    issue_id = await setup(env, guard=0)
    wrong = await env.post(f"/issues/{issue_id}/fixes", {"mode": "ai", "kind": "node_prompt_edit"})
    assert wrong.status_code == 422
    stale = await env.post(
        f"/issues/{issue_id}/fixes",
        {
            "mode": "manual",
            "kind": "prompt_edit",
            "payload": {"current_prompt": "An old prompt", "proposed_prompt": "New"},
        },
        key=False,
    )
    assert stale.status_code == 422 and stale.json()["type"].endswith("redraft-needed")
    same = await env.post(
        f"/issues/{issue_id}/fixes",
        {
            "mode": "manual",
            "kind": "prompt_edit",
            "payload": {"current_prompt": PROMPT, "proposed_prompt": PROMPT},
        },
        key=False,
    )
    assert same.status_code == 422 and same.json()["type"].endswith("no-change")


async def test_kb_attach_without_knowledge_is_advisory(issue_env: IssueEnv) -> None:
    env = issue_env
    issue_id = await setup(env, guard=0)
    fix = await draft(env, issue_id, kind="kb_attach")
    assert fix["status"] == "advisory" and fix["variant_config_hash"] is None
    assert fix["payload"]["uncovered_topics"]
    refused = await env.post(f"/issues/{issue_id}/validate", {})
    assert refused.status_code == 409 and refused.json()["type"].endswith("advisory-fix")
    detail = await env.issue(issue_id)
    assert detail["apply_blockers"] == ["advisory_fix"]


# US3 --------------------------------------------------------------------------------------------


async def test_dry_run_returns_estimate_only(issue_env: IssueEnv) -> None:
    env = issue_env
    issue_id = await setup(env)
    await draft(env, issue_id)
    estimate = await env.post(f"/issues/{issue_id}/validate", {"dry_run": True})
    assert estimate.status_code == 200, estimate.text
    body = estimate.json()
    assert (body["affected_calls"], body["guard_calls"], body["simulations"]) == (10, 5, 30)
    assert body["estimated_cost_usd"] > 0
    assert (await env.issue(issue_id))["status"] == "open"
    assert (
        owner_sql("select count(*) from simulation_experiments where issue_id = %s", (issue_id,))[0][0] == 0
    )


async def test_validation_passes_and_evidence_is_immutable(issue_env: IssueEnv) -> None:
    env = issue_env
    issue_id = await setup(env)
    fix = await draft(env, issue_id)
    attempt = await start_validation(env, issue_id)
    assert attempt["status"] == "running" and attempt["fix_revision"] == fix["revision"]
    assert len(attempt["affected_call_ids"]) == 10 and len(attempt["guard_call_ids"]) == 5
    assert attempt["thresholds"] == {"min_improvement_pp": 10.0, "max_regression_pp": 5.0, "min_sample": 5}
    detail = await env.issue(issue_id)
    assert detail["status"] == "validating" and detail["current_fix"]["status"] == "validating"
    exp = owner_sql(
        "select source, issue_id, target_type from simulation_experiments where id = %s",
        (attempt["treatment_experiment_id"],),
    )[0]
    assert exp == ("issue_validation", issue_id, "variant")
    busy = await env.post(f"/issues/{issue_id}/fixes", {"mode": "ai"})
    assert busy.status_code == 409 and busy.json()["type"].endswith("validation-running")

    latest = await finish(env, attempt, control_passes=2, treatment_passes=6)
    assert latest["status"] == "completed" and latest["decision"] == "passed"
    assert latest["headline"]["delta_pp"] == 40.0
    assert latest["headline"]["n"] == 10
    sets = {(e["evaluator_id"], e["set"]) for e in latest["evaluator_results"]}
    assert {(FACT, "affected"), (FACT, "guard"), (FACT, "combined")} <= sets
    detail = await env.issue(issue_id)
    assert detail["status"] == "validated" and detail["current_fix"]["status"] == "passed"
    assert detail["can_apply"] is True and detail["apply_blockers"] == []
    assert detail["current_fix"]["variant_config_hash"] == latest["variant_config_hash"]

    with (
        psycopg.connect(_sync_dsn(TEST_DB), autocommit=True) as conn,
        pytest.raises(psycopg.errors.CheckViolation),
    ):
        conn.execute("update issue_validations set decision = 'failed' where issue_id = %s", (issue_id,))


async def test_small_improvement_fails_and_returns_to_open(issue_env: IssueEnv) -> None:
    env = issue_env
    issue_id = await setup(env)
    await draft(env, issue_id)
    attempt = await start_validation(env, issue_id)
    latest = await finish(env, attempt, control_passes=2, treatment_passes=2)
    assert latest["decision"] == "failed"
    assert latest["reasons"][0]["code"] == "improvement_below_threshold"
    detail = await env.issue(issue_id)
    assert detail["status"] == "open" and detail["current_fix"]["status"] == "failed"
    assert detail["apply_blockers"] == ["no_passing_validation"]


async def test_regression_on_another_check_fails(issue_env: IssueEnv) -> None:
    env = issue_env
    issue_id = await setup(env)
    await draft(env, issue_id)
    attempt = await start_validation(env, issue_id)
    # Tool call correctness: every affected call passes in control and fails in treatment.
    latest = await finish(env, attempt, control_passes=2, treatment_passes=8, tools=("pass", "fail"))
    assert latest["decision"] == "failed"
    regression = next(r for r in latest["reasons"] if r["code"] == "regression")
    assert regression["evaluator_id"] == TOOLS and regression["set"] == "combined"


async def test_too_few_completed_runs_is_inconclusive(issue_env: IssueEnv) -> None:
    env = issue_env
    issue_id = await setup(env, failing=6, guard=0)
    await draft(env, issue_id)
    attempt = await start_validation(env, issue_id)
    latest = await finish(env, attempt, 0, 4, failed=tuple(attempt["affected_call_ids"][:2]))
    assert latest["decision"] == "inconclusive"
    codes = {r["code"] for r in latest["reasons"]}
    assert "insufficient_sample" in codes and "too_many_failed_runs" in codes
    assert (await env.issue(issue_id))["status"] == "open"


async def test_cancel_keeps_attempt_as_cancelled(issue_env: IssueEnv) -> None:
    env = issue_env
    issue_id = await setup(env)
    await draft(env, issue_id)
    attempt = await start_validation(env, issue_id)
    response = await env.post(f"/issues/{issue_id}/validation/cancel", key=False)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "open"
    assert response.json()["current_fix"]["status"] == "draft"
    [latest] = (await env.client.get(f"/v1/issues/{issue_id}/validations", headers=env.headers)).json()[
        "items"
    ]
    assert latest["status"] == "cancelled" and latest["attempt"] == attempt["attempt"]
    statuses = owner_sql(
        "select distinct status from simulation_runs where experiment_id = %s",
        (attempt["control_experiment_id"],),
    )
    assert statuses == [("cancelled",)]
    again = await env.post(f"/issues/{issue_id}/validation/cancel", key=False)
    assert again.status_code == 409


async def test_draft_and_validate_failure_keeps_failed_revision(issue_env: IssueEnv) -> None:
    env = issue_env
    issue_id = await setup(env)
    response = await env.post(f"/issues/{issue_id}/draft-and-validate", {})
    assert response.status_code == 202, response.text
    body = response.json()
    assert body["fix"]["revision"] == 1 and body["validation"]["auto"] is True
    latest = await finish(env, body["validation"], 3, 3)
    assert latest["decision"] == "failed"
    [fix] = (await env.client.get(f"/v1/issues/{issue_id}/fixes", headers=env.headers)).json()["items"]
    assert fix["status"] == "failed"
    assert (await env.issue(issue_id))["status"] == "open"


async def test_redrafting_a_validated_issue_returns_it_to_open(issue_env: IssueEnv) -> None:
    env = issue_env
    issue_id = await setup(env)
    await draft(env, issue_id)
    attempt = await start_validation(env, issue_id)
    await finish(env, attempt, 2, 8)
    assert (await env.issue(issue_id))["status"] == "validated"
    await draft(env, issue_id, kind="add_guardrail")
    detail = await env.issue(issue_id)
    assert detail["status"] == "open" and detail["apply_blockers"] == ["no_passing_validation"]
    revisions = (await env.client.get(f"/v1/issues/{issue_id}/fixes", headers=env.headers)).json()["items"]
    assert [f["status"] for f in revisions] == ["draft", "superseded"]


async def test_not_enough_calls_to_validate(issue_env: IssueEnv) -> None:
    env = issue_env
    issue_id = await setup(env, failing=4, guard=0)
    await draft(env, issue_id)
    refused = await env.post(f"/issues/{issue_id}/validate", {})
    assert refused.status_code == 422 and refused.json()["type"].endswith("not-enough-calls")
    ok = await env.post(f"/issues/{issue_id}/validate", {"min_sample": 3, "dry_run": True})
    assert ok.status_code == 200 and ok.json()["affected_calls"] == 4
