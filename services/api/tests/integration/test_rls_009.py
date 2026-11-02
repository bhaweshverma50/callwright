"""Issues tables deny cross-workspace access (009 T054; Principle V)."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from tests.conftest import make_workspace, signup
from tests.integration.test_issue_apply import validated
from tests.issues_support import IssueEnv

TABLES = (
    "issues",
    "issue_samples",
    "issue_failure_embeddings",
    "issue_fixes",
    "issue_validations",
    "issue_detection_runs",
)


async def test_issue_tables_are_isolated_per_workspace(app: FastAPI, issue_env: IssueEnv) -> None:
    env = issue_env
    issue_id, _ = await validated(env)
    async with app.state.db.transaction(workspace_id=env.ws) as session:
        own = {
            t: int((await session.execute(text(f"select count(*) from {t}"))).scalar_one()) for t in TABLES
        }
    assert all(own[t] > 0 for t in TABLES), own

    _, other_ws = await make_workspace(app)
    async with app.state.db.transaction(workspace_id=other_ws) as session:
        for table in TABLES:
            seen = (await session.execute(text(f"select count(*) from {table}"))).scalar_one()
            assert seen == 0, table
    with pytest.raises(DBAPIError):
        async with app.state.db.transaction(workspace_id=other_ws) as session:
            await session.execute(
                text("update issues set title = 'taken over' where id = :id returning id"), {"id": issue_id}
            )
            await session.execute(
                text(
                    "insert into issue_samples (issue_id, call_id, workspace_id, call_origin, failed_at) "
                    "values (:id, :call, :ws, 'live', now())"
                ),
                {"id": issue_id, "call": env.calls["fail"][0], "ws": env.ws},
            )

    stranger = await signup(env.client, app)
    for path in (
        f"/v1/issues/{issue_id}",
        f"/v1/issues/{issue_id}/fixes",
        f"/v1/issues/{issue_id}/validations",
    ):
        response = await env.client.get(path, headers=stranger.headers)
        assert response.status_code == 404, path
    listed = await env.client.get("/v1/issues", headers=stranger.headers)
    assert listed.json()["items"] == []
    apply = await env.client.post(f"/v1/issues/{issue_id}/apply", json={}, headers=stranger.headers)
    assert apply.status_code == 404
