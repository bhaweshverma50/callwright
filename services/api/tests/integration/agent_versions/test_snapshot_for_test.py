"""Test snapshots and get_snapshot for 003 (T055, FR-029, research R18)."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from app.agent_versions import service as versions
from app.agents import hooks
from tests.agent_helpers import create_ok
from tests.conftest import Account


async def test_unchanged_draft_reuses_draft_version(
    client: httpx.AsyncClient, account: Account, app: FastAPI
) -> None:
    agent = await create_ok(client, account)
    async with app.state.db.transaction(workspace_id=account.workspace_id) as session:
        snap = await versions.snapshot_for_test(session, agent["id"])
    assert snap.id == agent["draft_version"]["id"]


async def test_changed_resolved_tools_record_a_test_version(
    client: httpx.AsyncClient, account: Account, app: FastAPI
) -> None:
    tool_url = {"value": "https://tools.example.com/v1"}

    def tools(ctx: hooks.HookContext) -> list[dict[str, Any]]:
        return [{"tool_id": t, "url": tool_url["value"]} for t in ctx.config.get("tool_ids", [])]

    with hooks.registered(resolvers={"tools": tools}):
        agent = await create_ok(client, account, config={"prompt": "x", "tool_ids": ["tool_lookup"]})
        await client.put(
            f"/v1/agents/{agent['id']}/published-version",
            json={"version_id": agent["draft_version"]["id"]},
            headers=account.headers,
        )
        tool_url["value"] = "https://tools.example.com/v2"
        async with app.state.db.transaction(workspace_id=account.workspace_id) as session:
            snap = await versions.snapshot_for_test(session, agent["id"])
        async with app.state.db.transaction(workspace_id=account.workspace_id) as session:
            again = await versions.snapshot_for_test(session, agent["id"])
    assert snap.id != agent["draft_version"]["id"] and snap.source == "test"
    assert snap.created_by is None and snap.version_number == 2
    assert again.id == snap.id, "an identical draft reuses the test snapshot"
    assert snap.config["tools"] == [{"tool_id": "tool_lookup", "url": "https://tools.example.com/v2"}]
    detail = (await client.get(f"/v1/agents/{agent['id']}", headers=account.headers)).json()
    assert detail["published_version"]["id"] == agent["draft_version"]["id"]
    assert detail["draft_version"]["id"] == agent["draft_version"]["id"]
    hidden = (await client.get(f"/v1/agents/{agent['id']}/versions", headers=account.headers)).json()
    assert [v["source"] for v in hidden["items"]] == ["create"]
    shown = (
        await client.get(f"/v1/agents/{agent['id']}/versions?include_test=true", headers=account.headers)
    ).json()
    assert [v["source"] for v in shown["items"]] == ["test", "create"]


async def test_get_snapshot_and_get_published(
    client: httpx.AsyncClient, account: Account, app: FastAPI
) -> None:
    agent = await create_ok(client, account)
    version_id = agent["draft_version"]["id"]
    async with app.state.db.transaction(workspace_id=account.workspace_id) as session:
        snapshot = await versions.get_snapshot(session, version_id)
        assert await versions.get_published(session, agent["id"]) is None
    assert snapshot.version_id == version_id and snapshot.agent_id == agent["id"]
    assert snapshot.workspace_id == account.workspace_id and snapshot.version_number == 1
    assert snapshot.config == agent["draft_config"] and len(snapshot.content_hash) == 64
    assert snapshot.config["advanced"]["recording"] == "inherit"
    await client.put(
        f"/v1/agents/{agent['id']}/published-version",
        json={"version_id": version_id},
        headers=account.headers,
    )
    await client.delete(f"/v1/agents/{agent['id']}", headers=account.headers)
    async with app.state.db.transaction(workspace_id=account.workspace_id) as session:
        assert (await versions.get_snapshot(session, version_id)).version_id == version_id
        assert await versions.get_published(session, agent["id"]) is None, "deleted agents take no live calls"
        with pytest.raises(versions.VersionNotFound):
            await versions.get_snapshot(session, "agv_01ARZ3NDEKTSV4RRFFQ69G5FAV")


async def test_create_version_for_flow_publish(
    client: httpx.AsyncClient, account: Account, app: FastAPI
) -> None:
    agent = await create_ok(client, account, agent_type="flow", config={"prompt": ""})
    config = {**agent["draft_config"], "flow": {"flow_id": "flw_1", "graph": {"nodes": [{"id": "n_1"}]}}}
    async with app.state.db.transaction(workspace_id=account.workspace_id) as session:
        recorded = await versions.create_version(session, agent["id"], config, note="flow v1", publish=True)
    async with app.state.db.transaction(workspace_id=account.workspace_id) as session:
        again = await versions.create_version(session, agent["id"], config)
    assert recorded.created and not again.created and again.version.id == recorded.version.id
    assert recorded.version.source == "flow_publish" and recorded.version.summary["node_count"] == 1
    detail = (await client.get(f"/v1/agents/{agent['id']}", headers=account.headers)).json()
    assert detail["published_version"]["id"] == recorded.version.id
