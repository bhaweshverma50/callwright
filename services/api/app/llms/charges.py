"""Charging model usage: the one place that turns tokens and their list price into a feature
charge (001 ``billing.charge_feature``) with the feature markup, rounded up to $0.000001."""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.billing import service as billing
from app.llms.client import billable_cost
from app.llms.embeddings.base import EmbeddingAdapter
from app.pricing import engine
from app.pricing import service as pricing

# Rate used for an embedding model the catalog does not list (a new model).
FALLBACK_EMBEDDING_RATE = ("openai", "text-embedding-3-small")


async def embedding_cost(session: AsyncSession, embedder: EmbeddingAdapter, tokens: int) -> Decimal:
    """Vendor list price of embedding ``tokens``: the pricing catalog's per-1,000-token rate,
    rounded up to $0.000001. The offline fake costs nothing."""
    if embedder.provider == "fake":
        return Decimal(0)
    catalog = await pricing.catalog_at(session)
    rate = catalog.lookup("embedding", embedder.provider, embedder.model) or catalog.lookup(
        "embedding", *FALLBACK_EMBEDDING_RATE
    )
    return engine.price_embedding(rate, tokens) if rate is not None else Decimal(0)


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
    billable: bool = True,
) -> billing.FeatureCharge:
    """Charge ``tokens`` at ``raw_cost_usd`` list price once per ``idempotency_key`` (raises
    ``insufficient_credit`` at or below zero balance). ``billable=False`` records the usage and
    its cost without charging the workspace."""
    return await billing.charge_feature(
        session,
        workspace_id=workspace_id,
        feature_key=feature_key,
        quantity=Decimal(max(0, tokens)),
        unit="tokens",
        raw_cost_usd=raw_cost_usd,
        billable_cost_usd=billable_cost(raw_cost_usd) if billable else Decimal(0),
        idempotency_key=idempotency_key,
        ref_type=ref_type,
        ref_id=ref_id,
    )
