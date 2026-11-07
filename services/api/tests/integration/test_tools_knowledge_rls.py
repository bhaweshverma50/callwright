"""RLS isolation for the 005 tables (T007): rows of one workspace are invisible to another and
cannot be written into it."""

from __future__ import annotations

import pytest
import sqlalchemy.exc
from fastapi import FastAPI
from sqlalchemy import text

from app.agents.service import Actor
from app.core.secrets import key_wrapper
from app.knowledge import jobs
from app.tools import service as tools
from app.tools.schemas import ToolCreate
from tests.fixtures import knowledge as fx
from tests.knowledge_helpers import add_document, deps, new_kb, workspace

TABLES = ("tools", "knowledge_bases", "kb_documents", "kb_chunks")


async def _count(app: FastAPI, table: str, workspace_id: str | None, owner: str) -> int:
    async with app.state.db.transaction(workspace_id=workspace_id) as session:
        return int(
            (
                await session.execute(
                    text(f"select count(*) from {table} where workspace_id = :ws"), {"ws": owner}
                )
            ).scalar_one()
        )


async def test_tables_are_isolated(app: FastAPI) -> None:
    a = await workspace(app)
    b = await workspace(app)
    async with app.state.db.transaction(workspace_id=a.workspace_id) as session:
        await tools.create_tool(
            session,
            Actor(workspace_id=a.workspace_id, user_id=a.user_id),
            key_wrapper(app.state.settings),
            ToolCreate(type="end_call", name="end_call", description="End", config={}),
        )
    kb_id = await new_kb(app, a)
    doc_id = await add_document(app, a, kb_id, fx.refund_policy_pdf())
    await jobs.ingest(deps(app), doc_id)
    for table in TABLES:
        assert await _count(app, table, a.workspace_id, a.workspace_id) >= 1, table
        assert await _count(app, table, b.workspace_id, a.workspace_id) == 0, table
        assert await _count(app, table, None, a.workspace_id) == 0, table


async def test_cannot_write_into_another_workspace(app: FastAPI) -> None:
    a = await workspace(app)
    b = await workspace(app)
    with pytest.raises(sqlalchemy.exc.DBAPIError):
        async with app.state.db.transaction(workspace_id=b.workspace_id) as session:
            await session.execute(
                text("insert into knowledge_bases (id, workspace_id, name) values ('kb_x', :ws, 'Sneaky')"),
                {"ws": a.workspace_id},
            )
