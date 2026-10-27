"""Human labels (007 T045): one good/bad label and optional note per user per call."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class Annotation(Base):
    __tablename__ = "annotations"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String)
    call_id: Mapped[str] = mapped_column(String)
    user_id: Mapped[str] = mapped_column(String)
    user_display_name: Mapped[str] = mapped_column(String, default="")
    label: Mapped[str] = mapped_column(String)
    note: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
