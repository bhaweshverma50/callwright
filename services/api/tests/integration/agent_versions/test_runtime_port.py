"""``AgentVersionsAdapter``: 003's ``AgentVersionsPort`` over 002's service (wave 2 integration)."""

from __future__ import annotations

import httpx
from fastapi import FastAPI

from app.calls import ports
from app.calls.agent_versions import AgentVersionsAdapter
from tests.agent_helpers import PROMPT, create_ok, save_prompt
from tests.conftest import Account, signup

MISSING_VERSION = "agv_01ARZ3NDEKTSV4RRFFQ69G5FAV"


def test_create_app_registers_the_adapter(app: FastAPI) -> None:
    assert isinstance(ports.registry.agent_versions, AgentVersionsAdapter)


async def test_port_answers_from_the_agent_tables(
    app: FastAPI, client: httpx.AsyncClient, account: Account
) -> None:
    port = AgentVersionsAdapter()
    agent = await create_ok(client, account)
    v1 = agent["draft_version"]["id"]
    async with app.state.db.transaction(workspace_id=account.workspace_id) as session:
        assert await port.agent_exists(session, agent["id"])
        assert await port.get_published(session, agent["id"]) is None
        snapshot = await port.get_snapshot(session, v1)
        assert await port.get_snapshot(session, MISSING_VERSION) is None
        for_test = await port.snapshot_for_test(session, agent["id"])
    assert snapshot is not None and for_test is not None
    assert (snapshot.version_id, snapshot.agent_id, snapshot.workspace_id) == (
        v1,
        agent["id"],
        account.workspace_id,
    )
    assert snapshot.agent_type == "single_prompt" and snapshot.config["prompt"] == PROMPT
    assert for_test.version_id == v1  # an unchanged draft reuses its version

    published = await client.put(
        f"/v1/agents/{agent['id']}/published-version", json={"version_id": v1}, headers=account.headers
    )
    assert published.status_code == 200, published.text
    edited = await save_prompt(client, account, agent, "You answer calls for a bakery.")
    async with app.state.db.transaction(workspace_id=account.workspace_id) as session:
        live = await port.get_published(session, agent["id"])
        draft = await port.snapshot_for_test(session, agent["id"])
    assert live is not None and live.version_id == v1
    assert draft is not None and draft.version_id == edited["version"]["id"]
    assert draft.config["prompt"] == "You answer calls for a bakery."


async def test_other_workspaces_and_deleted_agents_are_invisible(
    app: FastAPI, client: httpx.AsyncClient, account: Account
) -> None:
    port = AgentVersionsAdapter()
    agent = await create_ok(client, account)
    other = await signup(client, app)
    async with app.state.db.transaction(workspace_id=other.workspace_id) as session:
        assert not await port.agent_exists(session, agent["id"])
        assert await port.get_snapshot(session, agent["draft_version"]["id"]) is None
        assert await port.snapshot_for_test(session, agent["id"]) is None
        assert await port.get_published(session, agent["id"]) is None

    assert (await client.delete(f"/v1/agents/{agent['id']}", headers=account.headers)).status_code == 204
    async with app.state.db.transaction(workspace_id=account.workspace_id) as session:
        assert not await port.agent_exists(session, agent["id"])
        assert await port.snapshot_for_test(session, agent["id"]) is None
        assert await port.get_published(session, agent["id"]) is None
        # A deleted agent's versions stay readable for the calls that ran on them.
        kept = await port.get_snapshot(session, agent["draft_version"]["id"])
    assert kept is not None and kept.agent_id == agent["id"]
