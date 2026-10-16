"""Agent rows (data-model.md section 1). The table is created by migration s002_0001.

As in 001, ORM mappings declare no foreign keys; the migration owns the (deferred) constraints.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class Agent(Base):
    __tablename__ = "agents"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String)
    name: Mapped[str] = mapped_column(String(80))
    type: Mapped[str] = mapped_column(String)
    language: Mapped[str] = mapped_column(String)
    draft_config: Mapped[dict[str, Any]] = mapped_column(JSONB)
    draft_revision: Mapped[int] = mapped_column(Integer, default=1)
    draft_version_id: Mapped[str] = mapped_column(String)
    pinned_version_id: Mapped[str | None] = mapped_column(String)
    template_id: Mapped[str | None] = mapped_column(String)
    created_by: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
