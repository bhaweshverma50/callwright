"""Dismissal and post-apply follow-up (009 T049; US5, FR-023, FR-024)."""

from __future__ import annotations

from tests.integration.test_issue_apply import validated
from tests.issues_support import FACT, IssueEnv, make_env, ready_issue
from tests.runtime_support import owner_sql


async def test_other_needs_a_note(issue_env: IssueEnv) -> None:
    env = issue_env
    issue = await ready_issue(env, 4)
    path = f"/issues/{issue['issue_id']}/dismiss"
    refused = await env.post(path, {"reason": "other"}, key=False)
    assert refused.status_code == 422
    blank = await env.post(path, {"reason": "other", "note": "   "}, key=False)
    assert blank.status_code == 422
    ok = await env.post(path, {"reason": "other", "note": "Seasonal pricing, already handled"}, key=False)
    assert ok.status_code == 200, ok.text
    body = ok.json()
    assert (body["status"], body["dismiss_reason"], body["dismiss_note"]) == (
        "dismissed",
        "other",
        "Seasonal pricing, already handled",
    )
    again = await env.post(path, {"reason": "wont_fix"}, key=False)
    assert again.status_code == 409 and again.json()["type"].endswith("wrong-status")


async def test_duplicate_needs_another_issue_of_the_same_agent(issue_env: IssueEnv) -> None:
    env = issue_env
    issue = await ready_issue(env, 4)
    env.seed_calls(4, reason="The agent never confirmed the appointment time back to the caller.", tag="b")
    await env.detect()
    issues = await env.issues()
    assert len(issues) == 2
    first, second = issues[0]["issue_id"], issues[1]["issue_id"]
    path = f"/issues/{first}/dismiss"
    assert (await env.post(path, {"reason": "duplicate"}, key=False)).status_code == 422
    assert (
        await env.post(path, {"reason": "duplicate", "duplicate_of": first}, key=False)
    ).status_code == 422
    other_env = await make_env(env.app, env.client)
    other_env.queue = env.queue
    foreign = await env.post(
        path, {"reason": "duplicate", "duplicate_of": "iss_01ARZ3NDEKTSV4RRFFQ69G5FAV"}, key=False
    )
    assert foreign.status_code == 422
    ok = await env.post(path, {"reason": "duplicate", "duplicate_of": second}, key=False)
    assert ok.status_code == 200 and ok.json()["duplicate_of"] == second
    assert issue["issue_id"] in (first, second)


async def test_dismiss_during_validation_cancels_it(issue_env: IssueEnv) -> None:
    env = issue_env
    issue = await ready_issue(env, 6)
    issue_id = issue["issue_id"]
    await env.post(f"/issues/{issue_id}/fixes", {"mode": "ai"})
    started = await env.post(f"/issues/{issue_id}/validate", {})
    assert started.status_code == 202
    attempt = started.json()
    ok = await env.post(f"/issues/{issue_id}/dismiss", {"reason": "evaluator_wrong"}, key=False)
    assert ok.status_code == 200 and ok.json()["status"] == "dismissed"
    [latest] = (await env.client.get(f"/v1/issues/{issue_id}/validations", headers=env.headers)).json()[
        "items"
    ]
    assert latest["status"] == "cancelled"
    for exp in (attempt["control_experiment_id"], attempt["treatment_experiment_id"]):
        assert (
            owner_sql("select status from simulation_experiments where id = %s", (exp,))[0][0] == "cancelled"
        )
    # A later detection updates its counts and it stays dismissed.
    env.seed_calls(2)
    await env.detect()
    assert (await env.issue(issue_id))["status"] == "dismissed"


async def test_post_apply_figures_appear_at_ten_calls(issue_env: IssueEnv) -> None:
    env = issue_env
    issue_id, _ = await validated(env)
    applied = await env.post(f"/issues/{issue_id}/apply", {}, key=False)
    version = applied.json()["agent_version_id"]
    env.seed_calls(9, verdict="pass", reason="ok", version_id=version, ago_hours=-1, tag="after")
    post = (await env.issue(issue_id))["post_apply"]
    assert post["ready"] is False and post["after"]["n"] == 9
    env.seed_calls(1, verdict="fail", version_id=version, ago_hours=-2, tag="after")
    post = (await env.issue(issue_id))["post_apply"]
    assert post["ready"] is True
    assert (post["after"]["n"], post["after"]["passes"], post["after"]["rate"]) == (10, 9, 0.9)
    # Before: the 8 failing calls and 3 passing guard calls on the base version.
    assert (post["before"]["n"], post["before"]["passes"]) == (11, 3)
    assert post["delta_pp"] == 62.7
    assert FACT
