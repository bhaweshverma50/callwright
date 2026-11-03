"""Scheduled callback rows (011, migration s011_0001)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.phone_numbers.models import pg_enum

STATUSES = ("scheduled", "placing", "placed", "cancelled", "failed")


class ScheduledCallback(Base):
    __tablename__ = "scheduled_callbacks"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String)
    phone_number_id: Mapped[str | None] = mapped_column(String)
    from_number: Mapped[str] = mapped_column(String)
    to_number: Mapped[str] = mapped_column(String)
    agent_id: Mapped[str | None] = mapped_column(String)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    timezone: Mapped[str] = mapped_column(String)
    recipient_timezones: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    timezone_source: Mapped[str] = mapped_column(
        pg_enum("timezone_source", "override", "number_region", "unknown")
    )
    note: Mapped[str] = mapped_column(String(500), default="")
    dynamic_variables: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    source_call_id: Mapped[str | None] = mapped_column(String)
    call_id: Mapped[str | None] = mapped_column(String)
    created_via: Mapped[str] = mapped_column(pg_enum("callback_origin", "agent", "api"))
    created_by_user_id: Mapped[str | None] = mapped_column(String)
    status: Mapped[str] = mapped_column(pg_enum("callback_status", *STATUSES), default="scheduled")
    failure_reason: Mapped[str | None] = mapped_column(String(64))
    failure_detail: Mapped[str | None] = mapped_column(String(500))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    placed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
