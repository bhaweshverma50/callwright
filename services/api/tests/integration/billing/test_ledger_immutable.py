"""The ledger is append-only for the app role (T019, Principle III)."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.core.db import Database
from tests.conftest import make_workspace


@pytest.mark.parametrize(
    "statement",
    [
        "update credit_transactions set amount_usd = 100 where workspace_id = :ws",
        "update credit_transactions set description = 'x' where workspace_id = :ws",
        "delete from credit_transactions where workspace_id = :ws",
    ],
)
async def test_update_and_delete_refused_for_app_role(app: FastAPI, db: Database, statement: str) -> None:
    _, ws = await make_workspace(app)
    with pytest.raises(DBAPIError, match="permission denied|append-only"):
        async with db.transaction(workspace_id=ws) as session:
            await session.execute(text(statement), {"ws": ws})


async def test_trigger_refuses_even_with_table_privileges(app: FastAPI, db: Database) -> None:
    """The admin role has no grants; the trigger is the second line behind the missing grants."""
    with pytest.raises(DBAPIError):
        async with db.admin_transaction() as session:
            await session.execute(text("delete from credit_transactions"))
