"""charge_feature money tests (T077, architecture section 7)."""

from __future__ import annotations

from decimal import Decimal

import pytest
from fastapi import FastAPI
from sqlalchemy import select

from app.billing import service
from app.billing.models import CreditTransaction
from app.core.errors import ProblemError
from app.core.ids import new_id
from app.usage.models import UsageEvent
from tests.conftest import make_workspace

D = Decimal


async def _charge(app: FastAPI, ws: str, billable: str, key: str, **kw: object) -> service.FeatureCharge:
    values: dict[str, object] = {
        "feature_key": "prompt_generation",
        "quantity": D("1"),
        "unit": "requests",
        "raw_cost_usd": D("0.002"),
        "billable_cost_usd": D(billable),
        "idempotency_key": key,
    }
    values.update(kw)
    async with app.state.db.transaction(workspace_id=ws) as session:
        return await service.charge_feature(session, workspace_id=ws, **values)  # type: ignore[arg-type]


async def _counts(app: FastAPI, ws: str) -> tuple[int, int]:
    async with app.state.db.transaction(workspace_id=ws) as session:
        txns = len(
            list(
                (
                    await session.execute(
                        select(CreditTransaction).where(CreditTransaction.type == "feature_charge")
                    )
                ).scalars()
            )
        )
        events = len(list((await session.execute(select(UsageEvent))).scalars()))
    return txns, events


async def test_feature_charge_writes_ledger_and_usage_rows(app: FastAPI) -> None:
    _, ws = await make_workspace(app)
    charge = await _charge(app, ws, "0.004", "k-1", ref_type="agent", ref_id=new_id("agt"))
    assert charge.created and charge.txn is not None
    assert charge.txn.amount_usd == D("-0.004000")
    assert charge.txn.feature_key == "prompt_generation"
    assert charge.usage_event.txn_id == charge.txn.id
    assert charge.usage_event.billable_cost_usd == D("0.004")
    assert await _counts(app, ws) == (1, 1)


async def test_idempotent_per_key(app: FastAPI) -> None:
    _, ws = await make_workspace(app)
    first = await _charge(app, ws, "0.004", "same-key")
    second = await _charge(app, ws, "0.004", "same-key")
    assert not second.created
    assert second.usage_event.id == first.usage_event.id
    assert second.txn is not None and first.txn is not None and second.txn.id == first.txn.id
    assert await _counts(app, ws) == (1, 1)


async def test_refused_at_or_below_zero(app: FastAPI) -> None:
    _, ws = await make_workspace(app, trial=False)
    with pytest.raises(ProblemError) as info:
        await _charge(app, ws, "0.004", "k")
    assert info.value.status == 402 and info.value.code == "insufficient_credit"
    assert await _counts(app, ws) == (0, 0)


async def test_eval_feature_keys(app: FastAPI) -> None:
    _, ws = await make_workspace(app)
    charge = await _charge(app, ws, "0.0004", "e-1", feature_key="eval.intent_fulfillment", unit="runs")
    assert charge.txn is not None and charge.txn.feature_key == "eval.intent_fulfillment"


@pytest.mark.parametrize(
    "overrides",
    [
        {"feature_key": "not_registered"},
        {"unit": "parsecs"},
        {"billable_cost_usd": D("-0.01")},
        {"raw_cost_usd": D("-0.01")},
        {"quantity": D("-1")},
        {"billable_cost_usd": D("0.0000001")},
        {"idempotency_key": ""},
    ],
)
async def test_invalid_inputs_rejected(app: FastAPI, overrides: dict[str, object]) -> None:
    _, ws = await make_workspace(app)
    with pytest.raises(ValueError):
        await _charge(app, ws, "0.01", "k", **overrides)
