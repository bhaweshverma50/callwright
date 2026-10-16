"""Versions are immutable and the agent type never changes (T023, FR-002, data-model section 2)."""

from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from tests.agent_helpers import create_ok
from tests.conftest import Account


async def test_update_and_delete_of_versions_refused(
    client: httpx.AsyncClient, account: Account, app: FastAPI
) -> None:
    agent = await create_ok(client, account)
    version_id = agent["draft_version"]["id"]
    db = app.state.db
    for statement in (
        "update agent_versions set note = 'changed' where id = :id",
        "delete from agent_versions where id = :id",
    ):
        with pytest.raises(DBAPIError):
            async with db.transaction(workspace_id=account.workspace_id) as session:
                await session.execute(text(statement), {"id": version_id})


async def test_agent_type_cannot_change(client: httpx.AsyncClient, account: Account, app: FastAPI) -> None:
    agent = await create_ok(client, account)
    with pytest.raises(DBAPIError):
        async with app.state.db.transaction(workspace_id=account.workspace_id) as session:
            await session.execute(text("update agents set type = 'flow' where id = :id"), {"id": agent["id"]})


async def test_published_version_must_belong_to_the_agent(
    client: httpx.AsyncClient, account: Account, app: FastAPI
) -> None:
    a = await create_ok(client, account, name="A")
    b = await create_ok(client, account, name="B")
    with pytest.raises(DBAPIError, match="does not belong"):
        async with app.state.db.transaction(workspace_id=account.workspace_id) as session:
            await session.execute(
                text("update agents set pinned_version_id = :v where id = :id"),
                {"v": b["draft_version"]["id"], "id": a["id"]},
            )
