"""Admission credit check (T050, FR-015, R13)."""

from __future__ import annotations

from decimal import Decimal

import psycopg
from fastapi import FastAPI

from app.billing import service
from app.core.ids import new_id
from tests.conftest import PG, TEST_DB, make_workspace


async def test_positive_balance_allowed(app: FastAPI) -> None:
    _, ws = await make_workspace(app)
    async with app.state.db.transaction(workspace_id=ws) as session:
        check = await service.credit_check(session, ws)
    assert check == service.CreditCheck(True, None, Decimal("5.000000"))


async def test_zero_balance_refused(app: FastAPI) -> None:
    _, ws = await make_workspace(app)
    async with app.state.db.transaction(workspace_id=ws) as session:
        await service.post_transaction(
            session,
            workspace_id=ws,
            type="call_charge",
            amount_usd=Decimal("-5"),
            description="c",
            call_id=new_id("call"),
        )
        check = await service.credit_check(session, ws)
    assert not check.allowed and check.reason == "insufficient_credit"


async def test_negative_balance_refused(app: FastAPI) -> None:
    _, ws = await make_workspace(app, trial=False)
    async with app.state.db.transaction(workspace_id=ws) as session:
        check = await service.credit_check(session, ws)
    assert check.reason == "insufficient_credit" and check.balance_usd == 0


async def test_unverified_owner_refused(app: FastAPI) -> None:
    user_id, ws = await make_workspace(app)
    with psycopg.connect(f"postgresql://callwright:callwright@{PG}/{TEST_DB}", autocommit=True) as conn:
        conn.execute("update users set email_verified_at = null where id = %s", (user_id,))
    async with app.state.db.transaction(workspace_id=ws) as session:
        check = await service.credit_check(session, ws)
    assert not check.allowed and check.reason == "email_unverified"


def test_grace_default(app: FastAPI) -> None:
    assert app.state.settings.credit_grace_usd == Decimal("0.50")
    assert app.state.settings.default_concurrency == 5
