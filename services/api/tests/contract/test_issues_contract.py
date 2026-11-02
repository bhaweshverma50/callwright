"""Every operation of contracts/issues.yaml against the live API (009 T013)."""

from __future__ import annotations

import uuid
from typing import Any

import httpx

from tests.contract.conftest import check
from tests.issues_support import FACT, IssueEnv, complete_batch, verdict_plan

MISSING = "iss_01ARZ3NDEKTSV4RRFFQ69G5FAV"


def key() -> dict[str, str]:
    return {"Idempotency-Key": f"c-{uuid.uuid4().hex}"}


async def post(env: IssueEnv, path: str, body: Any = None, *, idem: bool = True) -> httpx.Response:
    headers = {**env.headers, **(key() if idem else {})}
    return check(await env.client.post(f"/v1{path}", json=body if body is not None else {}, headers=headers))


async def get(env: IssueEnv, path: str, **params: Any) -> httpx.Response:
    return check(await env.client.get(f"/v1{path}", params=params, headers=env.headers))


async def test_issues_operations_match_the_contract(issue_env: IssueEnv) -> None:
    env = issue_env
    agent = env.agent.agent_id
    assert (await get(env, "/issues/detection", agent_id=agent)).json() is None
    env.seed_calls(8)
    env.seed_calls(3, verdict="pass", reason="ok", tag="guard", ago_hours=0.5)
    started = await post(env, "/issues/detect", {"agent_id": agent, "window_days": 14})
    assert started.status_code == 202
    assert (await post(env, "/issues/detect", {"agent_id": agent})).status_code == 409
    await env.run_jobs("detect_issues")
    assert (await get(env, "/issues/detection", agent_id=agent)).json()["status"] == "completed"

    listed = await get(env, "/issues", agent_id=agent, status="all", scope="real", window_days=14)
    [summary] = listed.json()["items"]
    issue_id = summary["issue_id"]
    assert (await get(env, f"/issues/{issue_id}")).status_code == 200
    assert (await get(env, f"/issues/{MISSING}")).status_code == 404
    assert (await get(env, f"/issues/{issue_id}/samples", page=1, page_size=5)).json()["total"] == 8

    assert (
        await post(env, f"/issues/{issue_id}/fixes", {"mode": "ai", "kind": "node_prompt_edit"})
    ).status_code == 422
    ai = await post(env, f"/issues/{issue_id}/fixes", {"mode": "ai"})
    assert ai.status_code == 201
    manual = await post(
        env,
        f"/issues/{issue_id}/fixes",
        {
            "mode": "manual",
            "kind": "add_guardrail",
            "payload": {"placement": "agent_prompt", "rule_text": "Quote only listed prices."},
        },
        idem=False,
    )
    assert manual.status_code == 201
    assert len((await get(env, f"/issues/{issue_id}/fixes")).json()["items"]) == 2

    assert (await post(env, f"/issues/{issue_id}/validate", {"dry_run": True})).status_code == 200
    attempt = (await post(env, f"/issues/{issue_id}/validate", {"mode": "persona"})).json()
    assert (await post(env, f"/issues/{issue_id}/validate", {})).status_code == 409
    assert (await post(env, f"/issues/{issue_id}/validation/cancel", idem=False)).status_code == 200
    assert (await post(env, f"/issues/{issue_id}/validation/cancel", idem=False)).status_code == 409
    assert (await post(env, f"/issues/{issue_id}/apply", {}, idem=False)).status_code == 409

    both = (await post(env, f"/issues/{issue_id}/draft-and-validate", {"kind": "add_guardrail"})).json()
    attempt = both["validation"]
    calls, guard = attempt["affected_call_ids"], {g: {FACT: "pass"} for g in attempt["guard_call_ids"]}
    complete_batch(env, attempt["control_experiment_id"], {**verdict_plan(calls, 1), **guard})
    complete_batch(env, attempt["treatment_experiment_id"], {**verdict_plan(calls, 7), **guard})
    await env.queue.enqueue("finalize_validation", env.ws, attempt["treatment_experiment_id"])
    await env.run_jobs("finalize_validation")
    validations = (await get(env, f"/issues/{issue_id}/validations")).json()["items"]
    assert [v["status"] for v in validations] == ["completed", "cancelled"]
    detail = (await get(env, f"/issues/{issue_id}")).json()
    assert detail["status"] == "validated"

    applied = await post(
        env, f"/issues/{issue_id}/apply", {"fix_revision": detail["current_fix"]["revision"]}, idem=False
    )
    assert applied.status_code == 200
    assert (
        await get(env, "/issues", applied_agent_version_id=applied.json()["agent_version_id"])
    ).status_code == 200
    assert (
        await post(env, f"/issues/{issue_id}/dismiss", {"reason": "wont_fix"}, idem=False)
    ).status_code == 409


async def test_dismiss_contract(issue_env: IssueEnv) -> None:
    env = issue_env
    env.seed_calls(4)
    await env.detect()
    [issue] = await env.issues()
    path = f"/issues/{issue['issue_id']}/dismiss"
    assert (await post(env, path, {"reason": "other"}, idem=False)).status_code == 422
    assert (await post(env, path, {"reason": "not_a_problem"}, idem=False)).status_code == 200
