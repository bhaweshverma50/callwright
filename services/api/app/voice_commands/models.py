"""Voice command audit rows (006 T079; table created by migration s006_0001)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, Boolean, DateTime, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class VoiceCommandLog(Base):
    __tablename__ = "voice_command_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    workspace_id: Mapped[str] = mapped_column(String)
    user_id: Mapped[str] = mapped_column(String)
    route: Mapped[str] = mapped_column(String)
    transcript: Mapped[str] = mapped_column(String)
    action: Mapped[str] = mapped_column(String)
    downgraded: Mapped[bool] = mapped_column(Boolean, default=False)
    raw_cost_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6), default=Decimal(0))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
