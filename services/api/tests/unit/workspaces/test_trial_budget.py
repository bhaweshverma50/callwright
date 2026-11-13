"""Daily trial-credit budget (Redis reservation per UTC date)."""

from __future__ import annotations

from decimal import Decimal

from redis.asyncio import Redis

from app.workspaces.service import _reserve_trial_credit, _trial_budget_key
from tests.conftest import REDIS_URL, make_settings

FIVE = Decimal("5.00")


async def test_unlimited_when_budget_unset_or_zero() -> None:
    for budget in (None, Decimal(0)):
        settings = make_settings(trial_credit_daily_budget_usd=budget)
        assert await _reserve_trial_credit(None, settings, FIVE) == FIVE


async def test_grants_until_budget_then_gives_back() -> None:
    redis = Redis.from_url(REDIS_URL)
    key = _trial_budget_key()
    await redis.delete(key)
    settings = make_settings(trial_credit_daily_budget_usd=Decimal("10"))
    try:
        assert await _reserve_trial_credit(redis, settings, FIVE) == FIVE
        assert await _reserve_trial_credit(redis, settings, FIVE) == FIVE
        assert await _reserve_trial_credit(redis, settings, FIVE) == 0
        assert Decimal((await redis.get(key)).decode()) == Decimal(10)
        assert 0 < await redis.ttl(key) <= 2 * 24 * 3600
    finally:
        await redis.delete(key)
        await redis.aclose()


async def test_grants_nothing_without_redis() -> None:
    settings = make_settings(trial_credit_daily_budget_usd=Decimal("10"))
    assert await _reserve_trial_credit(None, settings, FIVE) == 0
