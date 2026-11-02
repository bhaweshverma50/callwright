"""Issue list filters (009 T059; FR-026)."""

from __future__ import annotations

from tests.issues_support import OTHER_REASON, IssueEnv
from tests.runtime_support import owner_sql


async def test_window_scope_status_and_agent_filters(issue_env: IssueEnv) -> None:
    env = issue_env
    env.seed_calls(5)
    env.seed_calls(4, reason=OTHER_REASON, tag="other")
    await env.detect()
    issues = await env.issues()
    assert [i["affected_call_count"] for i in issues] == [5, 4]  # sorted by affected calls
    recent, old = issues[0]["issue_id"], issues[1]["issue_id"]
    owner_sql("update issues set last_seen_at = now() - interval '10 days' where id = %s", (old,))
    assert [i["issue_id"] for i in await env.issues(window_days=7)] == [recent]
    assert {i["issue_id"] for i in await env.issues(window_days=14)} == {recent, old}
    assert len(await env.issues()) == 2  # no window: every issue
    owner_sql("update issues set origin = 'simulated' where id = %s", (recent,))
    assert [i["issue_id"] for i in await env.issues(scope="real")] == [old]
    assert len(await env.issues(scope="real_and_simulated")) == 2
    assert [i["issue_id"] for i in await env.issues(scope="real_and_simulated", window_days=7)] == [recent]
    owner_sql("update issues set status = 'validated' where id = %s", (old,))
    assert [i["issue_id"] for i in await env.issues(status="validated")] == [old]
    assert await env.issues(status="open", scope="real") == []
    other = await env.client.get(
        "/v1/issues", params={"agent_id": "agt_01ARZ3NDEKTSV4RRFFQ69G5FAV"}, headers=env.headers
    )
    assert other.json()["items"] == []
    bad = await env.client.get("/v1/issues", params={"window_days": 5}, headers=env.headers)
    assert bad.status_code == 422
