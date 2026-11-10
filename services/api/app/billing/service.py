"""Credit ledger, top-ups, call and feature charges (research R10, R11, R13, R14).

Every credit movement goes through ``post_transaction``: a per-workspace advisory transaction
lock serialises writers, the next row gets ``seq + 1`` and ``balance_after = previous + amount``.
Idempotency comes from unique keys (``external_ref``, ``idempotency_key``, one call charge per
call, one trial grant per workspace); a repeat returns the existing row.

All functions take an ``AsyncSession`` already scoped to the workspace by
``Database.transaction(workspace_id=...)`` unless they take a ``Database``.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing.models import CallCost, CheckoutSession, CreditTransaction
from app.billing.stripe_gateway import StripeGateway
from app.core.db import Database
from app.core.errors import ProblemError, field_error, validation_failed
from app.core.ids import new_id
from app.core.pagination import page_window
from app.pricing import engine
from app.pricing import service as pricing
from app.pricing.features import is_valid_feature_key
from app.usage import service as usage_events
from app.usage.models import UsageEvent

logger = logging.getLogger(__name__)

TxnType = Literal["top_up", "call_charge", "feature_charge", "trial_grant", "refund", "adjustment"]
TXN_TYPES: tuple[str, ...] = (
    "top_up",
    "call_charge",
    "feature_charge",
    "trial_grant",
    "refund",
    "adjustment",
)
_CREDITS = frozenset({"top_up", "trial_grant", "refund"})
_DEBITS = frozenset({"call_charge", "feature_charge"})
_SIX = Decimal("0.000001")
ZERO = Decimal(0)
MIN_TOP_UP = Decimal("5.00")
MAX_TOP_UP = Decimal("10000.00")
USAGE_UNITS = frozenset({"minutes", "runs", "requests", "tokens", "k_tokens"})


class LedgerError(ValueError):
    """A ledger write broke a sign or precision rule."""


def insufficient_credit(detail: str = "Add funds to continue.") -> ProblemError:
    return ProblemError(402, "insufficient_credit", "Not enough credit", detail)


async def lock_workspace(session: AsyncSession, workspace_id: str) -> None:
    await session.execute(
        text("select pg_advisory_xact_lock(hashtextextended(:ws, 0))"), {"ws": workspace_id}
    )


@dataclass(frozen=True)
class Posted:
    txn: CreditTransaction
    created: bool


async def _existing_txn(
    session: AsyncSession,
    *,
    workspace_id: str,
    type: str,
    call_id: str | None,
    external_ref: str | None,
    idempotency_key: str | None,
) -> CreditTransaction | None:
    q = select(CreditTransaction)
    if external_ref is not None:
        hit = (await session.execute(q.where(CreditTransaction.external_ref == external_ref))).scalar()
        if hit is not None:
            return hit
    if idempotency_key is not None:
        hit = (
            await session.execute(
                q.where(
                    CreditTransaction.workspace_id == workspace_id,
                    CreditTransaction.idempotency_key == idempotency_key,
                )
            )
        ).scalar()
        if hit is not None:
            return hit
    if type == "call_charge" and call_id is not None:
        hit = (
            await session.execute(
                q.where(CreditTransaction.call_id == call_id, CreditTransaction.type == "call_charge")
            )
        ).scalar()
        if hit is not None:
            return hit
    if type == "trial_grant":
        return (
            await session.execute(
                q.where(
                    CreditTransaction.workspace_id == workspace_id, CreditTransaction.type == "trial_grant"
                )
            )
        ).scalar()
    return None


def _check_amount(type: str, amount: Decimal) -> Decimal:
    if type not in TXN_TYPES:
        raise LedgerError(f"unknown transaction type {type!r}")
    if amount != amount.quantize(_SIX):
        raise LedgerError("amounts carry at most six decimal places")
    if type in _CREDITS and amount <= 0:
        raise LedgerError(f"{type} must be positive")
    if type in _DEBITS and amount >= 0:
        raise LedgerError(f"{type} must be negative")
    if type == "adjustment" and amount == 0:
        raise LedgerError("adjustment must not be zero")
    return amount.quantize(_SIX)


async def latest_seq_and_balance(session: AsyncSession, workspace_id: str) -> tuple[int, Decimal]:
    row = (
        await session.execute(
            select(CreditTransaction.seq, CreditTransaction.balance_after_usd)
            .where(CreditTransaction.workspace_id == workspace_id)
            .order_by(CreditTransaction.seq.desc())
            .limit(1)
        )
    ).first()
    if row is None:
        return 0, ZERO
    return int(row.seq), Decimal(row.balance_after_usd)


async def post_transaction(
    session: AsyncSession,
    *,
    workspace_id: str,
    type: TxnType,
    amount_usd: Decimal,
    description: str,
    call_id: str | None = None,
    feature_key: str | None = None,
    external_ref: str | None = None,
    idempotency_key: str | None = None,
    created_by: str | None = None,
) -> Posted:
    """Append one ledger row, or return the existing row for the same idempotency key."""
    amount = _check_amount(type, amount_usd)
    await lock_workspace(session, workspace_id)
    existing = await _existing_txn(
        session,
        workspace_id=workspace_id,
        type=type,
        call_id=call_id,
        external_ref=external_ref,
        idempotency_key=idempotency_key,
    )
    if existing is not None:
        return Posted(existing, created=False)
    seq, balance = await latest_seq_and_balance(session, workspace_id)
    txn = CreditTransaction(
        id=new_id("txn"),
        workspace_id=workspace_id,
        seq=seq + 1,
        type=type,
        amount_usd=amount,
        balance_after_usd=balance + amount,
        call_id=call_id,
        feature_key=feature_key,
        external_ref=external_ref,
        idempotency_key=idempotency_key,
        description=description[:200],
        created_by=created_by,
    )
    session.add(txn)
    await session.flush()
    await session.refresh(txn)
    return Posted(txn, created=True)


async def get_balance(session: AsyncSession, workspace_id: str) -> Decimal:
    """Current balance: ``balance_after_usd`` of the latest row (0 when the ledger is empty)."""
    return (await latest_seq_and_balance(session, workspace_id))[1]


@dataclass(frozen=True)
class CreditCheck:
    allowed: bool
    reason: Literal["email_unverified", "insufficient_credit"] | None
    balance_usd: Decimal


async def credit_check(session: AsyncSession, workspace_id: str) -> CreditCheck:
    """Admission input for 003 (R13): refuse unverified owners and balances at or below zero."""
    verified = bool(
        (
            await session.execute(text("select app_workspace_owner_verified(:ws)"), {"ws": workspace_id})
        ).scalar()
    )
    balance = await get_balance(session, workspace_id)
    if not verified:
        return CreditCheck(False, "email_unverified", balance)
    if balance <= 0:
        return CreditCheck(False, "insufficient_credit", balance)
    return CreditCheck(True, None, balance)


async def list_transactions(
    session: AsyncSession,
    workspace_id: str,
    *,
    page: int,
    page_size: int,
    type: str | None = None,
) -> tuple[list[CreditTransaction], int]:
    where = [CreditTransaction.workspace_id == workspace_id]
    if type is not None:
        where.append(CreditTransaction.type == type)
    total = int(
        (
            await session.execute(select(func.count()).select_from(CreditTransaction).where(*where))
        ).scalar_one()
    )
    rows = (
        await session.execute(
            select(CreditTransaction)
            .where(*where)
            .order_by(CreditTransaction.seq.desc())
            .slice(*page_window(page, page_size))
        )
    ).scalars()
    return list(rows), total


async def get_transaction(
    session: AsyncSession, workspace_id: str, txn_id: str
) -> tuple[CreditTransaction, CallCost | None] | None:
    txn = (
        await session.execute(
            select(CreditTransaction).where(
                CreditTransaction.id == txn_id, CreditTransaction.workspace_id == workspace_id
            )
        )
    ).scalar_one_or_none()
    if txn is None:
        return None
    cost = None
    if txn.type == "call_charge" and txn.call_id is not None:
        cost = await session.get(CallCost, txn.call_id)
    return txn, cost


async def call_costs_for(session: AsyncSession, call_ids: list[str]) -> dict[str, CallCost]:
    if not call_ids:
        return {}
    rows = (await session.execute(select(CallCost).where(CallCost.call_id.in_(call_ids)))).scalars()
    return {row.call_id: row for row in rows}


def validate_top_up_amount(amount: Decimal) -> Decimal:
    """FR-008: at least $5.00, at most $10,000.00, whole cents."""
    errors = []
    if not amount.is_finite():
        errors.append(field_error("/amount_usd", "invalid_format", "Enter an amount in dollars and cents."))
    elif amount != amount.quantize(Decimal("0.01")):
        errors.append(field_error("/amount_usd", "too_precise", "Use whole cents (two decimal places)."))
    elif amount < MIN_TOP_UP:
        errors.append(field_error("/amount_usd", "out_of_range", "The minimum top-up is $5.00."))
    elif amount > MAX_TOP_UP:
        errors.append(field_error("/amount_usd", "out_of_range", "The maximum top-up is $10,000.00."))
    if errors:
        raise validation_failed(errors)
    return amount.quantize(Decimal("0.01"))


async def create_checkout(
    session: AsyncSession,
    gateway: StripeGateway,
    *,
    workspace_id: str,
    amount_usd: Decimal,
    web_base_url: str,
    idempotency_key: str | None,
) -> CheckoutSession:
    amount = validate_top_up_amount(amount_usd)
    if idempotency_key:
        existing = (
            await session.execute(
                select(CheckoutSession).where(
                    CheckoutSession.workspace_id == workspace_id,
                    CheckoutSession.idempotency_key == idempotency_key,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            return existing
    base = web_base_url.rstrip("/")
    created = await gateway.create_checkout_session(
        amount_usd=amount,
        workspace_id=workspace_id,
        success_url=f"{base}/billing?checkout=success",
        cancel_url=f"{base}/billing?checkout=canceled",
        idempotency_key=idempotency_key,
    )
    row = CheckoutSession(
        workspace_id=workspace_id,
        stripe_session_id=created.id,
        amount_usd=amount,
        status="pending",
        checkout_url=created.url,
        expires_at=created.expires_at,
        idempotency_key=idempotency_key,
    )
    session.add(row)
    await session.flush()
    return row


def _ref_id(value: Any) -> str | None:
    if isinstance(value, Mapping):
        value = value.get("id")
    return str(value) if value else None


def _usd_from_cents(cents: Any) -> Decimal:
    return (Decimal(int(cents)) / 100).quantize(Decimal("0.01"))


async def _workspace_for(db: Database, function: str, ref: str) -> str | None:
    async with db.transaction() as session:
        value = (await session.execute(text(f"select {function}(:ref)"), {"ref": ref})).scalar()
    return str(value) if value else None


async def handle_stripe_event(db: Database, event: Mapping[str, Any]) -> str:
    """Apply a verified Stripe event. Returns a short outcome label (for logs and tests)."""
    etype = str(event.get("type", ""))
    obj = event.get("data", {}).get("object", {}) or {}
    if etype in {"checkout.session.completed", "checkout.session.async_payment_succeeded"}:
        if obj.get("payment_status") != "paid":
            return "awaiting_payment"
        return await _complete_checkout(db, obj)
    if etype == "checkout.session.expired":
        return await _expire_checkout(db, obj)
    if etype == "charge.refunded":
        return await _refund(db, obj)
    if etype == "charge.dispute.created":
        return await _dispute(db, obj)
    return "ignored"


async def _complete_checkout(db: Database, obj: Mapping[str, Any]) -> str:
    stripe_session_id = str(obj.get("id", ""))
    workspace_id = await _workspace_for(db, "billing_checkout_workspace", stripe_session_id)
    if workspace_id is None:
        logger.warning("checkout completion for unknown session %s", stripe_session_id)
        return "unknown_session"
    async with db.transaction(workspace_id=workspace_id) as session:
        await lock_workspace(session, workspace_id)
        row = (
            await session.execute(
                select(CheckoutSession).where(CheckoutSession.stripe_session_id == stripe_session_id)
            )
        ).scalar_one()
        amount = (
            _usd_from_cents(obj["amount_total"]) if obj.get("amount_total") is not None else row.amount_usd
        )
        if amount != row.amount_usd:
            logger.warning("checkout %s paid %s, expected %s", stripe_session_id, amount, row.amount_usd)
        reference = _ref_id(obj.get("payment_intent")) or stripe_session_id
        posted = await post_transaction(
            session,
            workspace_id=workspace_id,
            type="top_up",
            amount_usd=Decimal(amount),
            description=f"Top-up ${Decimal(amount):,.2f}",
            external_ref=reference,
        )
        if row.status != "completed":
            row.status = "completed"
            row.txn_id = posted.txn.id
            row.completed_at = datetime.now(UTC)
            await session.flush()
    return "credited" if posted.created else "duplicate"


async def _expire_checkout(db: Database, obj: Mapping[str, Any]) -> str:
    stripe_session_id = str(obj.get("id", ""))
    workspace_id = await _workspace_for(db, "billing_checkout_workspace", stripe_session_id)
    if workspace_id is None:
        return "unknown_session"
    async with db.transaction(workspace_id=workspace_id) as session:
        row = (
            await session.execute(
                select(CheckoutSession)
                .where(CheckoutSession.stripe_session_id == stripe_session_id)
                .with_for_update()
            )
        ).scalar_one()
        if row.status != "pending":
            return "unchanged"
        row.status = "expired"
        await session.flush()
    return "expired"


async def _adjust_for_payment(
    db: Database, payment_intent: str | None, items: list[tuple[str, Decimal, str]]
) -> str:
    """Post negative adjustments ``(external_ref, positive amount, description)`` against the
    workspace that was credited by ``payment_intent``."""
    if not payment_intent:
        return "unknown_payment"
    workspace_id = await _workspace_for(db, "billing_workspace_for_external_ref", payment_intent)
    if workspace_id is None:
        logger.warning("refund or dispute for unknown payment %s", payment_intent)
        return "unknown_payment"
    created = 0
    async with db.transaction(workspace_id=workspace_id) as session:
        for ref, amount, description in items:
            if amount <= 0:
                continue
            posted = await post_transaction(
                session,
                workspace_id=workspace_id,
                type="adjustment",
                amount_usd=-amount,
                description=description,
                external_ref=ref,
            )
            created += int(posted.created)
    return "adjusted" if created else "duplicate"


async def _refund(db: Database, charge: Mapping[str, Any]) -> str:
    refunds = (charge.get("refunds") or {}).get("data") or []
    items: list[tuple[str, Decimal, str]] = []
    for refund in refunds:
        if refund.get("status") in {"failed", "canceled"}:
            continue
        items.append((str(refund["id"]), _usd_from_cents(refund["amount"]), f"Refund {refund['id']}"))
    if not items and charge.get("amount_refunded"):
        items.append(
            (
                f"{charge['id']}:refund",
                _usd_from_cents(charge["amount_refunded"]),
                f"Refund of {charge['id']}",
            )
        )
    return await _adjust_for_payment(db, _ref_id(charge.get("payment_intent")), items)


async def _dispute(db: Database, dispute: Mapping[str, Any]) -> str:
    items = [(str(dispute["id"]), _usd_from_cents(dispute["amount"]), f"Payment dispute {dispute['id']}")]
    return await _adjust_for_payment(db, _ref_id(dispute.get("payment_intent")), items)


@dataclass(frozen=True)
class CallUsage:
    """What 003 sends after a call: the AgentConfig components and summed CallEvent meters."""

    workspace_id: str
    call_id: str
    agent_version_id: str | None
    started_at: datetime
    duration_ms: int
    components: engine.Components
    meters: Mapping[str, int]


class PricingUnavailable(Exception):
    def __init__(self, components: tuple[str, ...]) -> None:
        super().__init__(f"unpriced components: {', '.join(components)}")
        self.components = components


def call_cost_json(row: CallCost) -> dict[str, Any]:
    return {
        "call_id": row.call_id,
        "catalog_version": row.catalog_version,
        "duration_ms": int(row.duration_ms),
        "billed_seconds": row.billed_seconds,
        "duration_minutes": engine.fmt6(Decimal(row.duration_minutes)),
        "lines": row.lines,
        "total_usd": engine.fmt6(Decimal(row.total_usd)),
    }


def _mmss(seconds: int) -> str:
    return f"{seconds // 60}:{seconds % 60:02d}"


async def charge_call(session: AsyncSession, usage: CallUsage) -> CallCost:
    """Price a finished call with the catalog in effect at its start and charge the ledger.

    Idempotent per ``call_id``: a repeat returns the stored breakdown. Never refuses for low
    balance (the call already happened; 003 enforces the grace amount mid-call).
    """
    await lock_workspace(session, usage.workspace_id)
    existing = await session.get(CallCost, usage.call_id)
    if existing is not None:
        return existing
    catalog = await pricing.catalog_at(session, usage.started_at)
    meters = engine.Usage(
        duration_ms=usage.duration_ms,
        llm_input_tokens=int(usage.meters.get("llm_input_tokens", 0)),
        llm_output_tokens=int(usage.meters.get("llm_output_tokens", 0)),
        tts_chars=int(usage.meters.get("tts_chars", 0)),
    )
    quote = engine.price(usage.components, meters, catalog)
    breakdown = quote.call
    assert breakdown is not None
    if not breakdown.complete:
        raise PricingUnavailable(breakdown.unpriced)
    txn_id: str | None = None
    if breakdown.total_usd > 0:
        posted = await post_transaction(
            session,
            workspace_id=usage.workspace_id,
            type="call_charge",
            amount_usd=-breakdown.total_usd,
            description=f"Call {usage.call_id} ({_mmss(breakdown.billed_seconds)})",
            call_id=usage.call_id,
        )
        txn_id = posted.txn.id
    row = CallCost(
        call_id=usage.call_id,
        workspace_id=usage.workspace_id,
        catalog_version=breakdown.catalog_version,
        duration_ms=breakdown.duration_ms,
        billed_seconds=breakdown.billed_seconds,
        duration_minutes=engine.q6(breakdown.duration_minutes),
        lines=[engine.cost_line_json(line) for line in breakdown.lines],
        total_usd=breakdown.total_usd,
        raw_cost_usd=engine.q6(breakdown.raw_cost_usd),
        txn_id=txn_id,
    )
    session.add(row)
    usage_events.record(
        session,
        workspace_id=usage.workspace_id,
        feature_key="calls",
        quantity=engine.q6(breakdown.duration_minutes),
        unit="minutes",
        raw_cost_usd=engine.q6(breakdown.raw_cost_usd),
        billable_cost_usd=breakdown.total_usd,
        ref_type="call",
        ref_id=usage.call_id,
        txn_id=txn_id,
        idempotency_key=f"call_charge:{usage.call_id}",
    )
    await session.flush()
    return row


@dataclass(frozen=True)
class FeatureCharge:
    usage_event: UsageEvent
    txn: CreditTransaction | None
    created: bool


async def charge_feature(
    session: AsyncSession,
    *,
    workspace_id: str,
    feature_key: str,
    quantity: Decimal,
    unit: str,
    raw_cost_usd: Decimal,
    billable_cost_usd: Decimal,
    idempotency_key: str,
    ref_type: str | None = None,
    ref_id: str | None = None,
    occurred_at: datetime | None = None,
) -> FeatureCharge:
    """Record a feature's usage and, when the billable amount is above zero, charge it.

    A zero billable amount writes the usage row only (no ledger row, allowed at any balance).
    A positive amount is refused with ``insufficient_credit`` when the balance is at or below
    zero. Idempotent per ``idempotency_key`` within the workspace.
    """
    if not is_valid_feature_key(feature_key):
        raise ValueError(f"unregistered feature key {feature_key!r}")
    if unit not in USAGE_UNITS:
        raise ValueError(f"unknown usage unit {unit!r}")
    if not idempotency_key:
        raise ValueError("idempotency_key is required")
    for name, value in (
        ("quantity", quantity),
        ("raw_cost_usd", raw_cost_usd),
        ("billable_cost_usd", billable_cost_usd),
    ):
        if value < 0:
            raise ValueError(f"{name} must not be negative")
    billable = billable_cost_usd.quantize(_SIX)
    if billable != billable_cost_usd:
        raise ValueError("billable_cost_usd carries at most six decimal places")
    await lock_workspace(session, workspace_id)
    existing = await usage_events.find(session, workspace_id, idempotency_key)
    if existing is not None:
        txn = await session.get(CreditTransaction, existing.txn_id) if existing.txn_id else None
        return FeatureCharge(existing, txn, created=False)
    txn = None
    if billable > 0:
        if await get_balance(session, workspace_id) <= 0:
            raise insufficient_credit()
        posted = await post_transaction(
            session,
            workspace_id=workspace_id,
            type="feature_charge",
            amount_usd=-billable,
            description=f"Feature {feature_key}",
            feature_key=feature_key,
            idempotency_key=idempotency_key,
        )
        txn = posted.txn
    event = usage_events.record(
        session,
        workspace_id=workspace_id,
        feature_key=feature_key,
        quantity=quantity.quantize(_SIX),
        unit=unit,
        raw_cost_usd=raw_cost_usd.quantize(_SIX),
        billable_cost_usd=billable,
        ref_type=ref_type,
        ref_id=ref_id,
        txn_id=txn.id if txn else None,
        idempotency_key=idempotency_key,
        occurred_at=occurred_at,
    )
    await session.flush()
    return FeatureCharge(event, txn, created=True)
