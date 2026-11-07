"""Apply a validated fix as a new agent version (009 T044; US4, FR-020 to FR-022, SC-001)."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest_asyncio
from fastapi import FastAPI

from app.agents import service as agents
from app.agents import versions
from app.issues.apply import normalised_hash
from app.issues.jobs import audit_applied_issues
from tests.conftest import signup
from tests.issues_support import FACT, TOOLS, IssueEnv, complete_batch, enable, ready_issue, verdict_plan
from tests.runtime_support import RecordingQueue, owner_sql
from tests.sim_support import make_agent


async def validated(env: IssueEnv, fix_body: dict[str, Any] | None = None) -> tuple[str, dict[str, Any]]:
    issue = await ready_issue(env, 8)
    issue_id = issue["issue_id"]
    env.seed_calls(3, verdict="pass", reason="ok", tag="guard", ago_hours=0.5)
    body = fix_body or {"mode": "ai"}
    fix = await env.post(f"/issues/{issue_id}/fixes", body, key=body.get("mode") == "ai")
    assert fix.status_code == 201, fix.text
    started = await env.post(f"/issues/{issue_id}/validate", {})
    assert started.status_code == 202, started.text
    attempt = started.json()
    calls = attempt["affected_call_ids"]
    guard = {g: {FACT: "pass"} for g in attempt["guard_call_ids"]}
    complete_batch(env, attempt["control_experiment_id"], {**verdict_plan(calls, 1), **guard})
    complete_batch(env, attempt["treatment_experiment_id"], {**verdict_plan(calls, 7), **guard})
    await env.queue.enqueue("finalize_validation", env.ws, attempt["control_experiment_id"])
    await env.run_jobs("finalize_validation")
    detail = await env.issue(issue_id)
    assert detail["status"] == "validated", detail["latest_validation"]
    return issue_id, detail


async def test_apply_creates_and_publishes_the_validated_version(issue_env: IssueEnv) -> None:
    env = issue_env
    issue_id, detail = await validated(env)
    response = await env.post(f"/issues/{issue_id}/apply", {}, key=False)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["published"] is True and body["tool_copies"] == [] and body["draft_updated"] is True
    version_id = body["agent_version_id"]
    assert body["release_notes"].startswith(f"Fix for {issue_id}: {detail['title']}")
    row = owner_sql("select content_hash, note, source from agent_versions where id = %s", (version_id,))[0]
    assert row[0] == detail["latest_validation"]["variant_config_hash"]
    assert issue_id in row[1]
    agent = owner_sql(
        "select pinned_version_id, draft_version_id, draft_config->>'prompt' from agents where id = %s",
        (env.agent.agent_id,),
    )[0]
    assert agent[0] == version_id and agent[1] == version_id
    assert agent[2] == detail["current_fix"]["payload"]["proposed_prompt"]
    issue = body["issue"]
    assert issue["status"] == "applied" and issue["applied_agent_version_id"] == version_id
    assert issue["current_fix"]["status"] == "applied"
    assert issue["post_apply"]["ready"] is False
    again = await env.post(f"/issues/{issue_id}/apply", {}, key=False)
    assert again.status_code == 409 and again.json()["type"].endswith("wrong-status")
    linked = (
        await env.client.get(
            "/v1/issues", params={"applied_agent_version_id": version_id}, headers=env.headers
        )
    ).json()["items"]
    assert [i["issue_id"] for i in linked] == [issue_id]
    assert await audit_applied_issues(env.ctx()) == 0


async def test_apply_refused_without_passing_validation(issue_env: IssueEnv) -> None:
    env = issue_env
    issue = await ready_issue(env, 6)
    await env.post(f"/issues/{issue['issue_id']}/fixes", {"mode": "ai"})
    refused = await env.post(f"/issues/{issue['issue_id']}/apply", {}, key=False)
    assert refused.status_code == 409 and refused.json()["type"].endswith("no-passing-validation")
    assert refused.json()["detail"] == "This fix has no passing validation. Validate it, then apply."


async def test_apply_refused_when_another_version_was_published(issue_env: IssueEnv) -> None:
    env = issue_env
    issue_id, _ = await validated(env)
    async with env.app.state.db.transaction(workspace_id=env.ws) as session:
        snapshot = await versions.get_snapshot(session, env.agent.version_id)
        config = versions.draft_part(snapshot.config)
        config["prompt"] = config["prompt"] + "\nBe brief."
        await agents.create_version(session, env.agent.agent_id, config, source="save", publish=True)
    detail = await env.issue(issue_id)
    assert "base_version_changed" in detail["apply_blockers"] and detail["can_apply"] is False
    refused = await env.post(f"/issues/{issue_id}/apply", {}, key=False)
    assert refused.status_code == 409 and refused.json()["type"].endswith("base-version-changed")


async def test_apply_refused_when_draft_changed(issue_env: IssueEnv) -> None:
    env = issue_env
    issue_id, _ = await validated(env)
    owner_sql(
        "update agents set draft_config = jsonb_set(draft_config, '{prompt}', '\"Changed by hand\"') "
        "where id = %s",
        (env.agent.agent_id,),
    )
    assert (await env.issue(issue_id))["apply_blockers"] == ["draft_changed"]
    refused = await env.post(f"/issues/{issue_id}/apply", {}, key=False)
    assert refused.status_code == 409 and refused.json()["type"].endswith("draft-changed")


async def test_create_version_only_leaves_published_version(issue_env: IssueEnv) -> None:
    env = issue_env
    issue_id, _ = await validated(env)
    response = await env.post(f"/issues/{issue_id}/apply", {"publish": False}, key=False)
    assert response.status_code == 200, response.text
    assert response.json()["published"] is False
    pinned = owner_sql("select pinned_version_id from agents where id = %s", (env.agent.agent_id,))[0][0]
    assert pinned == env.agent.version_id != response.json()["agent_version_id"]


async def test_concurrent_publish_is_serialised(issue_env: IssueEnv) -> None:
    env = issue_env
    issue_id, _ = await validated(env)

    async def publish_other() -> None:
        async with env.app.state.db.transaction(workspace_id=env.ws) as session:
            snapshot = await versions.get_snapshot(session, env.agent.version_id)
            config = versions.draft_part(snapshot.config)
            config["prompt"] = config["prompt"] + "\nAnother edit."
            await agents.create_version(session, env.agent.agent_id, config, source="save", publish=True)

    apply_task = env.post(f"/issues/{issue_id}/apply", {}, key=False)
    response, _ = await asyncio.gather(apply_task, publish_other())
    issue = await env.issue(issue_id)
    if response.status_code == 200:
        assert issue["status"] == "applied"
    else:
        assert response.status_code == 409 and issue["status"] == "validated"


TOOL = {
    "type": "http",
    "name": "lookup_price",
    "description": "Look up a price.",
    "config": {
        "url": "https://api.example.com/prices",
        "parameters": {
            "type": "object",
            "properties": {"service": {"type": "string"}},
            "required": ["service"],
        },
    },
}


@pytest_asyncio.fixture
async def tool_envs(app: FastAPI, client: httpx.AsyncClient) -> AsyncIterator[tuple[IssueEnv, str, str]]:
    from app.llms import runtime as model_runtime

    account = await signup(client, app)
    created = await client.post("/v1/tools", json=TOOL, headers=account.headers)
    assert created.status_code == 201, created.text
    tool_id = created.json().get("tool_id") or created.json()["id"]
    agent = await make_agent(client, account, tool_ids=[tool_id])
    other = await make_agent(client, account, tool_ids=[tool_id])
    enable(account.workspace_id, agent.agent_id, FACT, TOOLS)
    queue = RecordingQueue()
    previous = getattr(app.state, "jobs", None)
    app.state.jobs = queue
    model_runtime.runtime().queue = queue
    yield IssueEnv(app, client, account, agent, queue), tool_id, other.agent_id
    app.state.jobs = previous
    model_runtime.runtime().queue = previous


TOOL_FIX = "Look up the listed price of one service. Never guess a price."


async def test_shared_tool_is_copied_for_this_agent(tool_envs: tuple[IssueEnv, str, str]) -> None:
    env, tool_id, other_agent = tool_envs
    fix_body = {
        "mode": "manual",
        "kind": "tool_description_edit",
        "payload": {
            "tool_id": tool_id,
            "current_description": "Look up a price.",
            "proposed_description": TOOL_FIX,
        },
    }
    issue_id, detail = await validated(env, fix_body)
    response = await env.post(f"/issues/{issue_id}/apply", {}, key=False)
    assert response.status_code == 200, response.text
    body = response.json()
    [copy] = body["tool_copies"]
    assert copy["original_tool_id"] == tool_id and copy["copy_tool_id"] != tool_id
    original = owner_sql("select description from tools where id = %s", (tool_id,))[0][0]
    copied = owner_sql("select description, name from tools where id = %s", (copy["copy_tool_id"],))[0]
    assert original == "Look up a price." and copied == (TOOL_FIX, "lookup_price")
    config = owner_sql(
        "select config, content_hash from agent_versions where id = %s", (body["agent_version_id"],)
    )[0]
    assert config[0]["tool_ids"] == [copy["copy_tool_id"]]
    copies = owner_sql("select applied_tool_copies from issues where id = %s", (issue_id,))[0][0]
    assert normalised_hash(config[0], copies) == detail["latest_validation"]["variant_config_hash"]
    other = owner_sql("select draft_config->'tool_ids' from agents where id = %s", (other_agent,))[0][0]
    assert other == [tool_id]
    assert await audit_applied_issues(env.ctx()) == 0


async def test_unshared_tool_is_edited_in_place(app: FastAPI, client: httpx.AsyncClient) -> None:
    from app.llms import runtime as model_runtime

    account = await signup(client, app)
    created = await client.post(
        "/v1/tools", json={**TOOL, "name": "lookup_price_solo"}, headers=account.headers
    )
    tool_id = created.json().get("tool_id") or created.json()["id"]
    agent = await make_agent(client, account, tool_ids=[tool_id])
    enable(account.workspace_id, agent.agent_id, FACT)
    queue = RecordingQueue()
    previous = getattr(app.state, "jobs", None)
    app.state.jobs = queue
    model_runtime.runtime().queue = queue
    try:
        env = IssueEnv(app, client, account, agent, queue)
        issue_id, detail = await validated(
            env,
            {
                "mode": "manual",
                "kind": "tool_description_edit",
                "payload": {
                    "tool_id": tool_id,
                    "current_description": "Look up a price.",
                    "proposed_description": TOOL_FIX,
                },
            },
        )
        response = await env.post(f"/issues/{issue_id}/apply", {}, key=False)
        assert response.status_code == 200, response.text
        assert response.json()["tool_copies"] == []
        assert owner_sql("select description from tools where id = %s", (tool_id,))[0][0] == TOOL_FIX
        version_hash = owner_sql(
            "select content_hash from agent_versions where id = %s", (response.json()["agent_version_id"],)
        )[0][0]
        assert version_hash == detail["latest_validation"]["variant_config_hash"]
    finally:
        app.state.jobs = previous
        model_runtime.runtime().queue = previous
