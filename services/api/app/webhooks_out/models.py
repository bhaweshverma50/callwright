"""Workspace signing secrets and the outbound delivery log (003 T010, data-model section 4)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

WEBHOOK_EVENTS = ("call_started", "call_ended", "call_analyzed", "ping")
DELIVERY_STATUSES = ("pending", "delivering", "succeeded", "failed", "blocked")


class WebhookSigningSecret(Base):
    __tablename__ = "webhook_signing_secrets"

    workspace_id: Mapped[str] = mapped_column(String, primary_key=True)
    current_secret_id: Mapped[int] = mapped_column(BigInteger)
    previous_secret_id: Mapped[int | None] = mapped_column(BigInteger)
    previous_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    rotated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WebhookDelivery(Base):
    __tablename__ = "webhook_deliveries"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String)
    call_id: Mapped[str | None] = mapped_column(String)
    event: Mapped[str] = mapped_column(String)
    url: Mapped[str] = mapped_column(String)
    timeout_ms: Mapped[int] = mapped_column(Integer)
    body: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String, default="pending")
    attempts: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    redelivery_of: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
