"""Zero-amount feature charges (T102, FR-023)."""

from __future__ import annotations

from decimal import Decimal

import httpx
from fastapi import FastAPI
from sqlalchemy import select

from app.billing import service
from app.billing.models import CreditTransaction
from app.usage.models import UsageEvent
from tests.conftest import Account, make_workspace


async def _zero(app: FastAPI, ws: str, key: str) -> service.FeatureCharge:
    async with app.state.db.transaction(workspace_id=ws) as session:
        return await service.charge_feature(
            session,
            workspace_id=ws,
            feature_key="embedding",
            quantity=Decimal("1536"),
            unit="tokens",
            raw_cost_usd=Decimal("0.000031"),
            billable_cost_usd=Decimal("0"),
            idempotency_key=key,
            ref_type="call",
            ref_id="call_internal_embedding",
        )


async def test_zero_amount_writes_usage_only(app: FastAPI) -> None:
    _, ws = await make_workspace(app)
    charge = await _zero(app, ws, "emb-1")
    assert charge.created and charge.txn is None
    assert charge.usage_event.txn_id is None
    assert charge.usage_event.raw_cost_usd == Decimal("0.000031")
    async with app.state.db.transaction(workspace_id=ws) as session:
        assert await service.get_balance(session, ws) == Decimal("5")
        txns = list((await session.execute(select(CreditTransaction))).scalars())
    assert [t.type for t in txns] == ["trial_grant"]


async def test_zero_amount_repeat_is_a_no_op(app: FastAPI) -> None:
    _, ws = await make_workspace(app)
    first = await _zero(app, ws, "emb-2")
    second = await _zero(app, ws, "emb-2")
    assert not second.created and second.usage_event.id == first.usage_event.id
    other = await _zero(app, ws, "emb-3")
    assert other.created
    async with app.state.db.transaction(workspace_id=ws) as session:
        assert len(list((await session.execute(select(UsageEvent))).scalars())) == 2


async def test_zero_amount_allowed_at_zero_balance(app: FastAPI) -> None:
    _, ws = await make_workspace(app, trial=False)
    charge = await _zero(app, ws, "emb-4")
    assert charge.created and charge.txn is None


async def test_zero_amount_appears_in_usage_report(
    client: httpx.AsyncClient, app: FastAPI, account: Account
) -> None:
    await _zero(app, account.workspace_id, "emb-5")
    report = (await client.get("/v1/usage", headers=account.headers)).json()
    row = next(r for r in report["rows"] if r["feature"] == "embedding")
    assert row["event_count"] == 1
    assert row["billable_cost_usd"] == "0.000000"
    assert row["raw_cost_usd"] == "0.000031"


async def test_positive_amount_still_writes_both_rows(app: FastAPI) -> None:
    _, ws = await make_workspace(app)
    async with app.state.db.transaction(workspace_id=ws) as session:
        charge = await service.charge_feature(
            session,
            workspace_id=ws,
            feature_key="embedding",
            quantity=Decimal("1000"),
            unit="tokens",
            raw_cost_usd=Decimal("0.00002"),
            billable_cost_usd=Decimal("0.00002"),
            idempotency_key="emb-6",
        )
    assert charge.txn is not None and charge.usage_event.txn_id == charge.txn.id
