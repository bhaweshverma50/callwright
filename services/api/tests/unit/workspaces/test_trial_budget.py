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


def test_normalized_email_folds_gmail_aliases() -> None:
    from app.workspaces.service import normalized_email

    assert normalized_email("N.ame+1@GoogleMail.com") == "name@gmail.com"
    assert normalized_email("name@gmail.com") == "name@gmail.com"
    assert normalized_email("first.last+promo@example.com") == "first.last@example.com"


async def test_one_trial_per_mailbox() -> None:
    from app.workspaces.service import _claim_trial, _trial_claim_key

    redis = Redis.from_url(REDIS_URL)
    key = _trial_claim_key("probe.alias@gmail.com")
    await redis.delete(key)
    try:
        assert await _claim_trial(redis, "probe.alias@gmail.com") is True
        assert await _claim_trial(redis, "probealias+2@gmail.com") is False
        assert await _claim_trial(redis, "other.probe@gmail.com") is True
        assert await _claim_trial(None, "probe.alias@gmail.com") is True
    finally:
        await redis.delete(key, _trial_claim_key("other.probe@gmail.com"))
        await redis.aclose()
