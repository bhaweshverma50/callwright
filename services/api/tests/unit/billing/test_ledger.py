"""Ledger writer money tests (T018, research R10, FR-006, FR-007)."""

from __future__ import annotations

import asyncio
from decimal import Decimal

import pytest
from fastapi import FastAPI
from sqlalchemy import func, select

from app.billing import service
from app.billing.models import CreditTransaction
from app.core.db import Database
from app.core.ids import new_id
from tests.conftest import make_workspace

D = Decimal


async def _post(db: Database, ws: str, type: service.TxnType, amount: str, **kw: object) -> service.Posted:
    async with db.transaction(workspace_id=ws) as session:
        return await service.post_transaction(
            session, workspace_id=ws, type=type, amount_usd=D(amount), description=f"test {type}", **kw
        )  # type: ignore[arg-type]


async def _rows(db: Database, ws: str) -> list[CreditTransaction]:
    async with db.transaction(workspace_id=ws) as session:
        rows = await session.execute(
            select(CreditTransaction)
            .where(CreditTransaction.workspace_id == ws)
            .order_by(CreditTransaction.seq)
        )
        return list(rows.scalars())


async def test_balance_after_chain(app: FastAPI, db: Database) -> None:
    _, ws = await make_workspace(app)
    await _post(db, ws, "top_up", "25.000000", external_ref=f"pi_{new_id('txn')}")
    await _post(db, ws, "call_charge", "-0.477000", call_id=new_id("call"))
    await _post(db, ws, "feature_charge", "-0.000400", idempotency_key="k1", feature_key="eval.x")
    rows = await _rows(db, ws)
    assert [r.seq for r in rows] == [1, 2, 3, 4]
    assert [r.type for r in rows] == ["trial_grant", "top_up", "call_charge", "feature_charge"]
    previous = D(0)
    for row in rows:
        assert row.balance_after_usd == previous + row.amount_usd
        previous = row.balance_after_usd
    async with db.transaction(workspace_id=ws) as session:
        balance = await service.get_balance(session, ws)
        total = (
            await session.execute(
                select(func.sum(CreditTransaction.amount_usd)).where(CreditTransaction.workspace_id == ws)
            )
        ).scalar_one()
    assert balance == D("29.522600") == total


@pytest.mark.parametrize(
    ("type", "amount"),
    [
        ("top_up", "0"),
        ("top_up", "-1"),
        ("trial_grant", "-5"),
        ("refund", "0"),
        ("call_charge", "0"),
        ("call_charge", "1"),
        ("feature_charge", "0.5"),
        ("adjustment", "0"),
        ("top_up", "1.0000001"),
        ("bogus", "1"),
    ],
)
async def test_sign_and_precision_rules(app: FastAPI, db: Database, type: str, amount: str) -> None:
    _, ws = await make_workspace(app)
    with pytest.raises(service.LedgerError):
        await _post(db, ws, type, amount)  # type: ignore[arg-type]


async def test_adjustment_may_be_negative_or_positive(app: FastAPI, db: Database) -> None:
    _, ws = await make_workspace(app)
    await _post(db, ws, "adjustment", "-1.500000", external_ref=f"dp_{new_id('txn')}")
    await _post(db, ws, "adjustment", "0.250000", external_ref=f"adj_{new_id('txn')}")
    async with db.transaction(workspace_id=ws) as session:
        assert await service.get_balance(session, ws) == D("3.750000")


async def test_idempotent_by_external_ref(app: FastAPI, db: Database) -> None:
    _, ws = await make_workspace(app)
    ref = f"pi_{new_id('txn')}"
    first = await _post(db, ws, "top_up", "25", external_ref=ref)
    second = await _post(db, ws, "top_up", "25", external_ref=ref)
    assert first.created and not second.created
    assert second.txn.id == first.txn.id
    assert len(await _rows(db, ws)) == 2


async def test_idempotent_by_key(app: FastAPI, db: Database) -> None:
    _, ws = await make_workspace(app)
    first = await _post(db, ws, "feature_charge", "-0.01", idempotency_key="same")
    second = await _post(db, ws, "feature_charge", "-0.01", idempotency_key="same")
    assert not second.created and second.txn.id == first.txn.id


async def test_idempotent_by_call_id(app: FastAPI, db: Database) -> None:
    _, ws = await make_workspace(app)
    call = new_id("call")
    first = await _post(db, ws, "call_charge", "-0.477", call_id=call)
    second = await _post(db, ws, "call_charge", "-0.477", call_id=call)
    assert not second.created and second.txn.id == first.txn.id


async def test_trial_grant_once(app: FastAPI, db: Database) -> None:
    _, ws = await make_workspace(app)
    again = await _post(db, ws, "trial_grant", "5")
    assert not again.created
    assert len(await _rows(db, ws)) == 1


async def test_empty_ledger_balance_is_zero(app: FastAPI, db: Database) -> None:
    _, ws = await make_workspace(app, trial=False)
    async with db.transaction(workspace_id=ws) as session:
        assert await service.latest_seq_and_balance(session, ws) == (0, D(0))


async def test_concurrent_posts_serialise_without_gaps(app: FastAPI, db: Database) -> None:
    _, ws = await make_workspace(app)

    async def charge(i: int) -> None:
        await _post(db, ws, "feature_charge", "-0.010000", idempotency_key=f"c{i}")

    await asyncio.gather(*(charge(i) for i in range(20)))
    rows = await _rows(db, ws)
    assert [r.seq for r in rows] == list(range(1, 22))
    assert rows[-1].balance_after_usd == D("4.800000")
    previous = D(0)
    for row in rows:
        assert row.balance_after_usd == previous + row.amount_usd
        previous = row.balance_after_usd
