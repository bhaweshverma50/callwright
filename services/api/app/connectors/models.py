"""Connection rows (022 data-model.md). Tables come from migration s022_0001."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, Boolean, DateTime, String, Text, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class Connection(Base):
    """A Google account's access granted to a workspace. The refresh token is in ``secrets``."""

    __tablename__ = "connections"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String)
    provider: Mapped[str] = mapped_column(String, default="google")
    kind: Mapped[str] = mapped_column(String, default="oauth")
    account_subject: Mapped[str] = mapped_column(String)
    account_email: Mapped[str] = mapped_column(String)
    scopes: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    sheets_access: Mapped[bool] = mapped_column(Boolean, default=False)
    secret_name: Mapped[str] = mapped_column(String)
    health: Mapped[str] = mapped_column(String, default="healthy")
    health_reason: Mapped[str | None] = mapped_column(String)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ConnectorActivity(Base):
    """Append-only (the app role has SELECT and INSERT only)."""

    __tablename__ = "connector_activity"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    workspace_id: Mapped[str] = mapped_column(String)
    actor_user_id: Mapped[str | None] = mapped_column(String)
    action: Mapped[str] = mapped_column(String)
    subject_type: Mapped[str] = mapped_column(String)
    subject_id: Mapped[str] = mapped_column(String)
    detail: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
