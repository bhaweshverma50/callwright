"""Usage events: one row per charge, the source of the usage report (R14, FR-023)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, DateTime, Identity, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class UsageEvent(Base):
    __tablename__ = "usage_events"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String)
    feature_key: Mapped[str] = mapped_column(String)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    unit: Mapped[str] = mapped_column(String)
    raw_cost_usd: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    billable_cost_usd: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    ref_type: Mapped[str | None] = mapped_column(String)
    ref_id: Mapped[str | None] = mapped_column(String)
    txn_id: Mapped[str | None] = mapped_column(String)
    idempotency_key: Mapped[str | None] = mapped_column(String)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
