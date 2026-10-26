"""WhatsApp channel and caller route rows (010 data-model.md sections 2 and 3)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class WhatsAppChannel(Base):
    __tablename__ = "whatsapp_channels"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String)
    meta_phone_number_id: Mapped[str] = mapped_column(String)
    e164: Mapped[str] = mapped_column(String)
    label: Mapped[str] = mapped_column(String(100))
    # Names of 001 secrets; the values are never returned.
    access_token_secret: Mapped[str] = mapped_column(String)
    access_token_last4: Mapped[str] = mapped_column(String)
    verify_token_secret: Mapped[str] = mapped_column(String)
    verify_token_last4: Mapped[str] = mapped_column(String)
    verify_token_hash: Mapped[str] = mapped_column(String)
    app_secret_secret: Mapped[str] = mapped_column(String)
    graph_api_version: Mapped[str] = mapped_column(String)
    sip_credentials_secret: Mapped[str | None] = mapped_column(String)
    inbound_agent_id: Mapped[str | None] = mapped_column(String)
    inbound_webhook_url: Mapped[str | None] = mapped_column(String)
    lk_inbound_trunk_id: Mapped[str | None] = mapped_column(String)
    lk_dispatch_rule_id: Mapped[str | None] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, default="setup_incomplete")
    status_detail: Mapped[str | None] = mapped_column(String)
    credentials_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    calling_enabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    webhook_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_webhook_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WhatsAppCallerRoute(Base):
    __tablename__ = "whatsapp_caller_routes"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String)
    channel_id: Mapped[str] = mapped_column(String)
    caller_e164: Mapped[str] = mapped_column(String)
    agent_id: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
