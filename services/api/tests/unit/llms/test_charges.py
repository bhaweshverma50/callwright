"""Embedding list price: catalog rate, fallback for an unlisted model, nothing for the fake."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest

from app.llms import charges
from app.pricing import engine
from app.pricing import service as pricing

CATALOG = engine.Catalog(
    version=1,
    effective_from=datetime(2026, 1, 1, tzinfo=UTC),
    rates=(
        engine.Rate(
            "embedding", "openai", "text-embedding-3-small", "Small", Decimal("0.00002"), (), "k_tokens"
        ),
        engine.Rate("embedding", "acme", "big-embed", "Big", Decimal("0.0001"), (), "k_tokens"),
    ),
)


@pytest.fixture(autouse=True)
def _catalog(monkeypatch: pytest.MonkeyPatch) -> None:
    async def catalog_at(session: Any) -> engine.Catalog:
        return CATALOG

    monkeypatch.setattr(pricing, "catalog_at", catalog_at)


def _embedder(provider: str, model: str) -> Any:
    return SimpleNamespace(provider=provider, model=model)


async def test_catalog_rate() -> None:
    cost = await charges.embedding_cost(None, _embedder("acme", "big-embed"), 10_000)  # type: ignore[arg-type]
    assert cost == Decimal("0.001000")


async def test_unknown_model_uses_fallback_rate() -> None:
    cost = await charges.embedding_cost(None, _embedder("acme", "new-embed"), 10_000)  # type: ignore[arg-type]
    assert cost == Decimal("0.000200")


async def test_fake_provider_is_free() -> None:
    cost = await charges.embedding_cost(None, _embedder("fake", "fake-hash-1536"), 10_000)  # type: ignore[arg-type]
    assert cost == Decimal(0)
