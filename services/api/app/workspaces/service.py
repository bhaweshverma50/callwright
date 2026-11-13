"""Workspace bootstrap and settings (T037, T038, T089; research R7)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.billing import service as billing
from app.core.auth import Principal, resolve_subject
from app.core.config import Settings
from app.core.db import Database
from app.core.ids import new_id
from app.core.money import SIX
from app.workspaces.models import User, Workspace

logger = logging.getLogger(__name__)

TRIAL_BUDGET_TTL_S = 2 * 24 * 3600


@dataclass(frozen=True)
class Bootstrapped:
    user_id: str
    workspace_id: str
    created: bool


def default_workspace_name(email: str) -> str:
    local = email.split("@", 1)[0] or "My"
    return f"{local}'s workspace"[:80]


def _trial_budget_key() -> str:
    return f"trial_budget:{datetime.now(UTC).date().isoformat()}"


GMAIL_DOMAINS = frozenset({"gmail.com", "googlemail.com"})


def normalized_email(email: str) -> str:
    """The mailbox an address really reaches: ``+tags`` dropped everywhere, and for Gmail the dots
    too (``N.ame+1@googlemail.com`` and ``name@gmail.com`` are one inbox)."""
    local, _, domain = email.strip().lower().rpartition("@")
    local = local.split("+", 1)[0]
    if domain in GMAIL_DOMAINS:
        local, domain = local.replace(".", ""), "gmail.com"
    return f"{local}@{domain}"


def _trial_claim_key(email: str) -> str:
    return f"trial_claimed:{normalized_email(email)}"


async def _claim_trial(redis: Redis | None, email: str) -> bool:
    """One trial per real mailbox, so aliases of one Gmail account cannot each collect it.

    ponytail: the claim lives in Redis (persisted on the VM, no TTL) to avoid a migration; if
    Redis is ever wiped, mailboxes can claim once more. A users-table column is the upgrade.
    Without Redis (local dev) every signup may claim; a Redis error grants nothing.
    """
    if redis is None:
        return True
    try:
        return bool(await redis.set(_trial_claim_key(email), "1", nx=True))
    except Exception:
        logger.warning("trial credit not granted: trial claim check failed", exc_info=True)
        return False


async def _reserve_trial_credit(redis: Redis | None, settings: Settings, amount: Decimal) -> Decimal:
    """Trial credit this signup may receive under TRIAL_CREDIT_DAILY_BUDGET_USD (the amount, or 0).

    The day's total is reserved atomically in Redis (one key per UTC date). A reservation that
    pushes the total over the budget is given back. Without Redis the grant is refused: failing
    safe means the workspace starts at zero rather than spending past the cap.
    """
    budget = settings.trial_credit_daily_budget_usd
    if amount <= 0 or not budget or budget <= 0:
        return amount
    if redis is None:
        logger.warning("trial credit not granted: daily budget is set but Redis is unavailable")
        return Decimal(0)
    key = _trial_budget_key()
    try:
        async with redis.pipeline(transaction=True) as pipe:
            pipe.incrbyfloat(key, float(amount))
            pipe.expire(key, TRIAL_BUDGET_TTL_S)
            total, _ = await pipe.execute()
        if Decimal(str(total)) > budget:
            await redis.incrbyfloat(key, -float(amount))
            logger.warning("trial credit not granted: daily budget %s reached (reserved %s)", budget, total)
            return Decimal(0)
    except Exception:
        logger.warning("trial credit not granted: daily budget check failed", exc_info=True)
        return Decimal(0)
    return amount


async def _release_trial_credit(redis: Redis | None, settings: Settings, amount: Decimal) -> None:
    budget = settings.trial_credit_daily_budget_usd
    if redis is None or amount <= 0 or not budget or budget <= 0:
        return
    try:
        await redis.incrbyfloat(_trial_budget_key(), -float(amount))
    except Exception:
        logger.warning("could not give back reserved trial credit", exc_info=True)


async def bootstrap_workspace(
    db: Database, settings: Settings, *, subject: str, email: str, redis: Redis | None = None
) -> Bootstrapped:
    """Create the user, workspace and trial grant in one transaction, once per IdP subject.

    Called on email verification (and on sign-in when a verified IdP user has no workspace yet).
    ``redis`` backs the daily trial-credit budget; when that budget is set and Redis is missing
    or down, the workspace is created with no trial credit.
    """
    row = await resolve_subject(db, subject)
    if row is not None and row.workspace_id is not None:
        return Bootstrapped(row.user_id, row.workspace_id, created=False)
    user_id = row.user_id if row is not None else new_id("usr")
    workspace_id = new_id("ws")
    trial = Decimal(settings.trial_credit_usd)
    if trial > 0 and not await _claim_trial(redis, email):
        logger.info("trial credit not granted: this mailbox already had one")
        trial = Decimal(0)
    grant = await _reserve_trial_credit(redis, settings, trial)
    try:
        async with db.transaction(workspace_id=workspace_id, user_id=user_id) as session:
            if row is None:
                session.add(
                    User(
                        id=user_id,
                        idp_subject=subject,
                        email=email.lower(),
                        email_verified_at=datetime.now(UTC),
                        is_admin=False,
                    )
                )
                await session.flush()
            session.add(
                Workspace(
                    id=workspace_id,
                    name=default_workspace_name(email),
                    owner_user_id=user_id,
                    concurrency_limit=settings.default_concurrency,
                    recording_default=True,
                )
            )
            await session.flush()
            if grant > 0:
                await billing.post_transaction(
                    session,
                    workspace_id=workspace_id,
                    type="trial_grant",
                    amount_usd=grant.quantize(SIX),
                    description="Trial credit",
                )
    except Exception as exc:
        await _release_trial_credit(redis, settings, grant)
        if not isinstance(exc, IntegrityError):
            raise
        # A concurrent verification won the race; return what it created.
        again = await resolve_subject(db, subject)
        if again is None or again.workspace_id is None:
            raise exc
        return Bootstrapped(again.user_id, again.workspace_id, created=False)
    return Bootstrapped(user_id, workspace_id, created=True)


@dataclass(frozen=True)
class MeView:
    user: User
    workspace: Workspace
    balance_usd: Decimal


async def get_me(db: Database, principal: Principal) -> MeView:
    async with db.transaction(workspace_id=principal.workspace_id, user_id=principal.user_id) as session:
        user = (await session.execute(select(User).where(User.id == principal.user_id))).scalar_one()
        workspace = (
            await session.execute(select(Workspace).where(Workspace.id == principal.workspace_id))
        ).scalar_one()
        balance = await billing.get_balance(session, principal.workspace_id)
    return MeView(user, workspace, balance)


async def update_workspace(
    db: Database, principal: Principal, *, name: str | None, recording_default: bool | None
) -> Workspace:
    async with db.transaction(workspace_id=principal.workspace_id, user_id=principal.user_id) as session:
        workspace = (
            await session.execute(select(Workspace).where(Workspace.id == principal.workspace_id))
        ).scalar_one()
        if name is not None:
            workspace.name = name
        if recording_default is not None:
            workspace.recording_default = recording_default
        await session.flush()
        return workspace
