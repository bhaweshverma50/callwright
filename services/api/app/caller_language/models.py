"""Caller language rows (012, migration s012_0001)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class CallerPreference(Base):
    __tablename__ = "caller_preferences"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String)
    phone_number: Mapped[str] = mapped_column(String)
    preferred_language: Mapped[str] = mapped_column(String(16))
    last_call_id: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CallLanguage(Base):
    __tablename__ = "call_languages"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String)
    call_id: Mapped[str] = mapped_column(String)
    kind: Mapped[str] = mapped_column(String)
    language: Mapped[str] = mapped_column(String(16))
    offset_ms: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
