"""Issue detection end to end through the API and the job (009 T016; US1, FR-001 to FR-006, SC-004)."""

from __future__ import annotations

import uuid

from tests.issues_support import FACT, OTHER_REASON, PRICE_REASON, TOOLS, IssueEnv, enable
from tests.quality_support import seed_label
from tests.runtime_support import owner_sql


async def test_detect_groups_recurring_failures_and_redetects_without_duplicates(issue_env: IssueEnv) -> None:
    env = issue_env
    env.seed_calls(20, verdict="pass", reason="Prices match the list.", tag="ok")
    env.seed_calls(8, reason=PRICE_REASON)
    env.seed_calls(2, reason=OTHER_REASON, tag="other")
    first = await env.detect()
    assert first["status"] == "completed"
    assert first["calls_scanned"] == 30
    assert first["failures_scanned"] == 10
    assert (first["issues_created"], first["issues_updated"]) == (1, 0)
    assert first["window_days"] == 14
    [issue] = await env.issues()
    assert issue["affected_call_count"] == 8
    assert issue["current_version_call_count"] == 8
    assert issue["evaluator_id"] == FACT
    assert issue["status"] == "open" and issue["origin"] == "real"
    assert 1 <= len(issue["title"]) <= 80
    detail = await env.issue(issue["issue_id"])
    assert detail["allowed_fix_kinds"][0] == detail["recommended_fix_kind"] == "prompt_edit"
    assert len(detail["sample_preview"]) == 5
    assert detail["sample_preview"][0]["reason_excerpt"] == PRICE_REASON
    samples = await env.client.get(f"/v1/issues/{issue['issue_id']}/samples", headers=env.headers)
    assert samples.json()["total"] == 8
    assert {s["call_id"] for s in samples.json()["items"]} == set(env.calls["fail"])

    second = await env.detect()
    assert (second["issues_created"], second["issues_updated"]) == (0, 1)
    assert len(await env.issues()) == 1


async def test_concurrent_detection_is_refused(issue_env: IssueEnv) -> None:
    env = issue_env
    body = {"agent_id": env.agent.agent_id}
    first = await env.client.post(
        "/v1/issues/detect", json=body, headers={**env.headers, "Idempotency-Key": f"a-{uuid.uuid4().hex}"}
    )
    assert first.status_code == 202
    again = await env.client.post(
        "/v1/issues/detect", json=body, headers={**env.headers, "Idempotency-Key": f"b-{uuid.uuid4().hex}"}
    )
    assert again.status_code == 409
    assert again.json()["type"].endswith("detection-running")
    await env.run_jobs("detect_issues")
    latest = (await env.client.get("/v1/issues/detection", params=body, headers=env.headers)).json()
    assert latest["status"] == "completed" and latest["issues_created"] == 0


async def test_no_failures_completes_with_window(issue_env: IssueEnv) -> None:
    env = issue_env
    never = await env.client.get(
        "/v1/issues/detection", params={"agent_id": env.agent.agent_id}, headers=env.headers
    )
    assert never.status_code == 200 and never.json() is None
    result = await env.detect(window_days=7)
    assert result["status"] == "completed" and result["issues_created"] == 0
    assert result["window_start"] < result["window_end"]


async def test_simulated_scope_marks_origin_and_list_filter(issue_env: IssueEnv) -> None:
    env = issue_env
    env.seed_calls(6, origin="simulation")
    real_only = await env.detect()
    assert real_only["failures_scanned"] == 0
    both = await env.detect(include_simulated=True)
    assert both["issues_created"] == 1
    assert await env.issues() == []  # scope=real hides mostly simulated issues
    [issue] = await env.issues(scope="real_and_simulated")
    assert issue["origin"] == "simulated"


async def test_disabled_evaluator_is_ignored(issue_env: IssueEnv) -> None:
    env = issue_env
    env.seed_calls(5, evaluator=TOOLS, reason="Called the booking tool twice.")
    enable(env.ws, env.agent.agent_id, TOOLS, enabled=False)
    result = await env.detect()
    assert result["failures_scanned"] == 0 and result["issues_created"] == 0


async def test_window_excludes_old_calls(issue_env: IssueEnv) -> None:
    env = issue_env
    env.seed_calls(5, ago_hours=24 * 20)
    assert (await env.detect())["issues_created"] == 0
    assert (await env.detect(window_days=30))["issues_created"] == 1


async def test_dismissed_issue_is_not_recreated_and_counts_update(issue_env: IssueEnv) -> None:
    env = issue_env
    env.seed_calls(4)
    await env.detect()
    [issue] = await env.issues()
    response = await env.post(f"/issues/{issue['issue_id']}/dismiss", {"reason": "wont_fix"}, key=False)
    assert response.status_code == 200 and response.json()["status"] == "dismissed"
    env.seed_calls(3)
    result = await env.detect()
    assert (result["issues_created"], result["issues_updated"]) == (0, 1)
    assert await env.issues() == []
    [dismissed] = await env.issues(status="dismissed")
    assert dismissed["affected_call_count"] == 7


async def test_calibration_warning_on_low_agreement(issue_env: IssueEnv) -> None:
    env = issue_env
    calls = env.seed_calls(6)
    for call in calls:  # people say every one of these calls was good: the check disagrees
        seed_label(env.ws, call, env.account.user_id, "good")
    await env.detect()
    [issue] = await env.issues()
    assert issue["calibration_warning"] is True


async def test_flow_node_attribution_and_turn_collapse(issue_env: IssueEnv) -> None:
    env = issue_env
    items = [
        {
            "node": "n_address1",
            "label": "Collect address",
            "verdict": "fail",
            "rationale": "Never read back the zip code.",
        },
        {
            "node": "n_address1",
            "label": "Collect address",
            "verdict": "fail",
            "rationale": "Never read back the zip code.",
        },
        {"node": "n_greeting", "label": "Greeting", "verdict": "pass", "rationale": "ok"},
    ]
    env.seed_calls(3, items=items, reason="Address step failed.")
    await env.detect()
    [issue] = await env.issues()
    assert issue["flow_node_id"] == "n_address1"
    assert issue["flow_node_label"] == "Collect address"
    assert issue["affected_call_count"] == 3


async def test_recurrence_after_apply(issue_env: IssueEnv) -> None:
    env = issue_env
    env.seed_calls(4)
    await env.detect()
    [issue] = await env.issues()
    # Mark it applied on a new version created now, then seed failures on that version.
    new_version = env.agent.version_id
    owner_sql("update agent_versions set created_at = now() where id = %s", (new_version,))
    owner_sql(
        "update issues set status = 'applied', applied_agent_version_id = %s, "
        "applied_at = now() - interval '1 minute' "
        "where id = %s",
        (new_version, issue["issue_id"]),
    )
    owner_sql("delete from issue_samples where issue_id = %s", (issue["issue_id"],))
    owner_sql(
        "update calls set ended_at = now() - interval '30 days' where id = any(%s)", (env.calls["fail"],)
    )
    env.seed_calls(3, ago_hours=0)
    result = await env.detect()
    assert result["issues_created"] == 1
    [recurrence] = await env.issues(status="open")
    assert recurrence["recurrence_of"] == issue["issue_id"]
    again = await env.detect()
    assert again["issues_created"] == 0
