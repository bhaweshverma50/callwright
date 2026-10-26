"""Outbound compliance rows (010 data-model.md sections 7 to 9)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, Identity, String, Text, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.phone_numbers.models import pg_enum


class DncEntry(Base):
    __tablename__ = "dnc_entries"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String)
    e164: Mapped[str] = mapped_column(String)
    note: Mapped[str | None] = mapped_column(String(200))
    source: Mapped[str] = mapped_column(pg_enum("dnc_source", "manual", "csv_import"))
    import_batch_id: Mapped[str | None] = mapped_column(String)
    created_by_user_id: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class OutboundCallingHours(Base):
    __tablename__ = "outbound_calling_hours"

    workspace_id: Mapped[str] = mapped_column(String, primary_key=True)
    windows: Mapped[dict[str, Any]] = mapped_column(JSONB)
    updated_by_user_id: Mapped[str | None] = mapped_column(String)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class OutboundPolicyDecision(Base):
    __tablename__ = "outbound_policy_decisions"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    reason: Mapped[str] = mapped_column(
        pg_enum("outbound_block_reason", "dnc_listed", "outside_calling_hours")
    )
    to_number: Mapped[str] = mapped_column(String)
    from_number: Mapped[str] = mapped_column(String)
    phone_number_id: Mapped[str | None] = mapped_column(String)
    agent_id: Mapped[str | None] = mapped_column(String)
    requested_by: Mapped[str] = mapped_column(String)
    idempotency_key: Mapped[str | None] = mapped_column(String)
    dnc_entry_id: Mapped[str | None] = mapped_column(String)
    dnc_e164: Mapped[str | None] = mapped_column(String)
    recipient_timezones: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    timezone_source: Mapped[str | None] = mapped_column(
        pg_enum("timezone_source", "override", "number_region", "unknown")
    )
    recipient_local_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=False))
    next_allowed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
