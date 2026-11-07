"""Usage events and the usage report per feature family for a date window (T079, research R14,
FR-014, FR-023). Events are written only through ``record`` (by 001 billing's charges)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import field_error, validation_failed
from app.pricing.features import FAMILIES, feature_family
from app.usage.models import UsageEvent

DEFAULT_DAYS = 30
MAX_DAYS = 366
ZERO = Decimal(0)


async def find(session: AsyncSession, workspace_id: str, idempotency_key: str) -> UsageEvent | None:
    return (
        await session.execute(
            select(UsageEvent).where(
                UsageEvent.workspace_id == workspace_id, UsageEvent.idempotency_key == idempotency_key
            )
        )
    ).scalar_one_or_none()


def record(
    session: AsyncSession,
    *,
    workspace_id: str,
    feature_key: str,
    quantity: Decimal,
    unit: str,
    raw_cost_usd: Decimal,
    billable_cost_usd: Decimal,
    ref_type: str | None,
    ref_id: str | None,
    txn_id: str | None,
    idempotency_key: str,
    occurred_at: datetime | None = None,
) -> UsageEvent:
    """Add one usage event to the session (flushed with the caller's charge)."""
    event = UsageEvent(
        workspace_id=workspace_id,
        feature_key=feature_key,
        quantity=quantity,
        unit=unit,
        raw_cost_usd=raw_cost_usd,
        billable_cost_usd=billable_cost_usd,
        ref_type=ref_type,
        ref_id=ref_id,
        txn_id=txn_id,
        idempotency_key=idempotency_key,
        occurred_at=occurred_at or datetime.now(UTC),
    )
    session.add(event)
    return event


@dataclass
class Detail:
    feature_key: str
    event_count: int
    raw_cost_usd: Decimal
    billable_cost_usd: Decimal


@dataclass
class Row:
    feature: str
    event_count: int = 0
    raw_cost_usd: Decimal = ZERO
    billable_cost_usd: Decimal = ZERO
    details: list[Detail] = field(default_factory=list)


@dataclass
class Report:
    start: date
    end: date
    rows: list[Row]
    total_raw_cost_usd: Decimal
    total_billable_cost_usd: Decimal


def resolve_window(start: date | None, end: date | None, today: date | None = None) -> tuple[date, date]:
    """Inclusive dates. Default ``to`` is today (UTC), default ``from`` 30 days before ``to``."""
    end = end or today or datetime.now(UTC).date()
    start = start or end - timedelta(days=DEFAULT_DAYS)
    if end < start:
        raise validation_failed(
            [field_error("/to", "out_of_range", "The end date is before the start date.")]
        )
    if (end - start).days + 1 > MAX_DAYS:
        raise validation_failed(
            [field_error("/from", "out_of_range", f"The window can cover at most {MAX_DAYS} days.")]
        )
    return start, end


async def report(session: AsyncSession, workspace_id: str, start: date | None, end: date | None) -> Report:
    start, end = resolve_window(start, end)
    lower = datetime.combine(start, time.min, UTC)
    upper = datetime.combine(end + timedelta(days=1), time.min, UTC)
    result = await session.execute(
        select(
            UsageEvent.feature_key,
            func.count(),
            func.coalesce(func.sum(UsageEvent.raw_cost_usd), 0),
            func.coalesce(func.sum(UsageEvent.billable_cost_usd), 0),
        )
        .where(
            UsageEvent.workspace_id == workspace_id,
            UsageEvent.occurred_at >= lower,
            UsageEvent.occurred_at < upper,
        )
        .group_by(UsageEvent.feature_key)
        .order_by(UsageEvent.feature_key)
    )
    rows: dict[str, Row] = {}
    for key, count, raw, billable in result.all():
        try:
            family = feature_family(key)
        except ValueError:
            continue
        if family not in FAMILIES:
            continue
        row = rows.setdefault(family, Row(family))
        detail = Detail(key, int(count), Decimal(raw), Decimal(billable))
        row.details.append(detail)
        row.event_count += detail.event_count
        row.raw_cost_usd += detail.raw_cost_usd
        row.billable_cost_usd += detail.billable_cost_usd
    ordered = sorted(rows.values(), key=lambda r: r.feature)
    return Report(
        start=start,
        end=end,
        rows=ordered,
        total_raw_cost_usd=sum((r.raw_cost_usd for r in ordered), ZERO),
        total_billable_cost_usd=sum((r.billable_cost_usd for r in ordered), ZERO),
    )
