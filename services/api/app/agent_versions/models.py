"""Agent version rows (data-model.md section 2). Immutable: the app role may only insert and a
trigger refuses updates and deletes."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class AgentVersion(Base):
    __tablename__ = "agent_versions"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String)
    agent_id: Mapped[str] = mapped_column(String)
    version_number: Mapped[int] = mapped_column(Integer)
    schema_version: Mapped[int] = mapped_column(Integer)
    config: Mapped[dict[str, Any]] = mapped_column(JSONB)
    content_hash: Mapped[str] = mapped_column(String(64))
    source: Mapped[str] = mapped_column(String)
    restored_from_version_id: Mapped[str | None] = mapped_column(String)
    parent_version_id: Mapped[str | None] = mapped_column(String)
    summary: Mapped[dict[str, Any]] = mapped_column(JSONB)
    note: Mapped[str | None] = mapped_column(String(500))
    publish_blockers: Mapped[list[dict[str, str]]] = mapped_column(JSONB, default=list)
    created_by: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
