"""Charging model usage: the one place that turns tokens and their list price into a feature
charge (001 ``billing.charge_feature``) with the feature markup, rounded up to $0.000001."""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.billing import service as billing
from app.llms.client import billable_cost


async def charge_tokens(
    session: AsyncSession,
    *,
    workspace_id: str,
    feature_key: str,
    idempotency_key: str,
    tokens: int,
    raw_cost_usd: Decimal,
    ref_type: str | None = None,
    ref_id: str | None = None,
) -> billing.FeatureCharge:
    """Charge ``tokens`` at ``raw_cost_usd`` list price once per ``idempotency_key`` (raises
    ``insufficient_credit`` at or below zero balance)."""
    return await billing.charge_feature(
        session,
        workspace_id=workspace_id,
        feature_key=feature_key,
        quantity=Decimal(max(0, tokens)),
        unit="tokens",
        raw_cost_usd=raw_cost_usd,
        billable_cost_usd=billable_cost(raw_cost_usd),
        idempotency_key=idempotency_key,
        ref_type=ref_type,
        ref_id=ref_id,
    )
