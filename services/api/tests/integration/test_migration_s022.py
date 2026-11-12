"""Migration s022_0001 (022 T006): the Drive sync tables are tenant tables, the activity log is
append-only, documents can be archived, and the security-definer lookups return ids only."""

from __future__ import annotations

import pytest
import sqlalchemy.exc
from fastapi import FastAPI
from sqlalchemy import text

from tests.knowledge_helpers import workspace

NEW_TABLES = ("connections", "kb_sources", "kb_source_files", "kb_sync_runs", "connector_activity")
FUNCTIONS = {
    "kb_sources_due": "id, workspace_id",
    "kb_sources_workspace_for": None,
    "kb_documents_archived_before": "id, workspace_id",
    "kb_sync_runs_before": "id, workspace_id",
}


async def test_new_tables_force_rls_with_tenant_policy(app: FastAPI) -> None:
    async with app.state.db.transaction() as session:
        for table in NEW_TABLES:
            row = (
                await session.execute(
                    text(
                        "select relrowsecurity, relforcerowsecurity from pg_class "
                        "where relname = :t and relkind = 'r'"
                    ),
                    {"t": table},
                )
            ).one()
            assert row == (True, True), table
            policy = (
                await session.execute(
                    text("select count(*) from pg_policies where tablename = :t and policyname = :p"),
                    {"t": table, "p": f"{table}_tenant"},
                )
            ).scalar_one()
            assert policy == 1, table


async def test_activity_is_append_only(app: FastAPI) -> None:
    ws = await workspace(app)
    async with app.state.db.transaction(workspace_id=ws.workspace_id) as session:
        await session.execute(
            text(
                "insert into connector_activity (workspace_id, action, subject_type, subject_id) "
                "values (:ws, 'connection_added', 'connection', 'conn_x')"
            ),
            {"ws": ws.workspace_id},
        )
    for statement in (
        "update connector_activity set action = 'connection_removed'",
        "delete from connector_activity",
    ):
        with pytest.raises(sqlalchemy.exc.DBAPIError):
            async with app.state.db.transaction(workspace_id=ws.workspace_id) as session:
                await session.execute(text(statement))


async def test_documents_accept_archived_status_and_source(app: FastAPI) -> None:
    async with app.state.db.transaction() as session:
        check = (
            await session.execute(
                text(
                    "select pg_get_constraintdef(oid) from pg_constraint "
                    "where conname = 'kb_documents_status_check'"
                )
            )
        ).scalar_one()
        assert "archived" in check
        columns = {
            r[0]
            for r in (
                await session.execute(
                    text(
                        "select column_name from information_schema.columns where table_name = 'kb_documents'"
                    )
                )
            ).all()
        }
        assert {"archived_at", "source_id"} <= columns


async def test_security_definer_lookups(app: FastAPI) -> None:
    async with app.state.db.transaction() as session:
        for name, columns in FUNCTIONS.items():
            row = (
                await session.execute(
                    text(
                        "select p.prosecdef, pg_get_function_result(p.oid) from pg_proc p "
                        "where p.proname = :n"
                    ),
                    {"n": name},
                )
            ).one()
            assert row[0] is True, name
            if columns:
                assert row[1] == f"TABLE({', '.join(c + ' text' for c in columns.split(', '))})", name
            else:
                assert row[1] == "text", name
