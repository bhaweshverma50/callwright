"""Feature charges of detection and drafting (009 T011; spec FR-025, research R9)."""

from __future__ import annotations

from decimal import Decimal

from fastapi import FastAPI
from sqlalchemy import func, select

from app.billing.models import CreditTransaction
from app.issues.charges import DETECT, DRAFT_FIX, charge, detect_key, draft_key, raw_cost
from app.pricing.features import feature_family
from app.usage.models import UsageEvent
from tests.conftest import make_workspace


def test_feature_keys_are_in_the_issues_family() -> None:
    assert feature_family(DETECT) == feature_family(DRAFT_FIX) == "issues"


def test_each_revision_is_charged_separately() -> None:
    assert draft_key("iss_A", 3) != draft_key("iss_A", 4)


def test_raw_cost_prices_tokens_and_embeddings() -> None:
    tokens_only = raw_cost("openai/gpt-5-mini", 1000, 200)
    assert tokens_only > 0 and raw_cost("gpt-5-mini", 1000, 200) == tokens_only
    embed = Decimal("0.0001")
    assert raw_cost("openai/gpt-5-mini", 1000, 200, embed_raw=embed) == tokens_only + embed
    assert raw_cost("openai/gpt-5-mini", 0, 0, embed_raw=embed) == embed


async def _counts(app: FastAPI, ws: str, key: str) -> tuple[int, int]:
    async with app.state.db.transaction(workspace_id=ws) as session:
        usage = (
            await session.execute(
                select(func.count()).select_from(UsageEvent).where(UsageEvent.idempotency_key == key)
            )
        ).scalar_one()
        txns = (
            await session.execute(
                select(func.count())
                .select_from(CreditTransaction)
                .where(CreditTransaction.idempotency_key == key)
            )
        ).scalar_one()
    return int(usage), int(txns)


async def test_draft_charge_is_recorded_once(app: FastAPI) -> None:
    _, ws = await make_workspace(app)
    key = draft_key("iss_charge", 1)
    raw = raw_cost("openai/gpt-5-mini", 4000, 600)
    billed_each: list[Decimal] = []
    for _ in range(2):
        async with app.state.db.transaction(workspace_id=ws) as session:
            billed = await charge(
                session,
                workspace_id=ws,
                feature_key=DRAFT_FIX,
                key=key,
                raw=raw,
                tokens=4600,
                ref_type="issue",
                ref_id="iss_charge",
            )
        billed_each.append(billed)
    assert billed_each[0] == billed_each[1] > raw
    assert await _counts(app, ws, key) == (1, 1)


async def test_zero_cost_detection_records_usage_without_ledger_row(app: FastAPI) -> None:
    _, ws = await make_workspace(app, trial=False)
    key = detect_key("run-zero")
    async with app.state.db.transaction(workspace_id=ws) as session:
        billed = await charge(
            session,
            workspace_id=ws,
            feature_key=DETECT,
            key=key,
            raw=Decimal(0),
            tokens=0,
            ref_type="agent",
            ref_id="agt_x",
        )
    assert billed == Decimal(0)
    assert await _counts(app, ws, key) == (1, 0)
