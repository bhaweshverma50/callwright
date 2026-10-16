"""Ledger, checkout sessions and call cost breakdowns (data-model.md)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import BigInteger, DateTime, Identity, Integer, Numeric, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

MONEY = Numeric(18, 6)


class CreditTransaction(Base):
    """Append-only: the app role has SELECT and INSERT only and a trigger refuses changes."""

    __tablename__ = "credit_transactions"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String)
    seq: Mapped[int] = mapped_column(BigInteger)
    type: Mapped[str] = mapped_column(String)
    amount_usd: Mapped[Decimal] = mapped_column(MONEY)
    balance_after_usd: Mapped[Decimal] = mapped_column(MONEY)
    call_id: Mapped[str | None] = mapped_column(String)
    feature_key: Mapped[str | None] = mapped_column(String)
    external_ref: Mapped[str | None] = mapped_column(String, unique=True)
    idempotency_key: Mapped[str | None] = mapped_column(String)
    description: Mapped[str] = mapped_column(String(200))
    created_by: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CheckoutSession(Base):
    __tablename__ = "checkout_sessions"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String)
    stripe_session_id: Mapped[str] = mapped_column(String, unique=True)
    amount_usd: Mapped[Decimal] = mapped_column(MONEY)
    status: Mapped[str] = mapped_column(String, default="pending")
    checkout_url: Mapped[str] = mapped_column(String)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    idempotency_key: Mapped[str | None] = mapped_column(String)
    txn_id: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CallCost(Base):
    __tablename__ = "call_costs"

    call_id: Mapped[str] = mapped_column(String, primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String)
    catalog_version: Mapped[int] = mapped_column(Integer)
    duration_ms: Mapped[int] = mapped_column(BigInteger)
    billed_seconds: Mapped[int] = mapped_column(Integer)
    duration_minutes: Mapped[Decimal] = mapped_column(MONEY)
    lines: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    total_usd: Mapped[Decimal] = mapped_column(MONEY)
    raw_cost_usd: Mapped[Decimal] = mapped_column(MONEY)
    txn_id: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
