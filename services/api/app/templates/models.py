"""Template rows (data-model.md section 6): global, read-only for the app role."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class Template(Base):
    __tablename__ = "templates"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    category: Mapped[str] = mapped_column(String)
    name: Mapped[str] = mapped_column(String(80))
    description: Mapped[str] = mapped_column(String(300))
    icon: Mapped[str] = mapped_column(String)
    direction: Mapped[str] = mapped_column(String)
    agent_type: Mapped[str] = mapped_column(String, server_default="single_prompt")
    config: Mapped[dict[str, Any]] = mapped_column(JSONB)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    content_hash: Mapped[str] = mapped_column(String)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
