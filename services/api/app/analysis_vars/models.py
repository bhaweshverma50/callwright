"""Analysis variables and per-call analyses (007 T017, data-model.md). Tables from s007_0001."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import DateTime, Integer, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class AnalysisVariable(Base):
    __tablename__ = "analysis_variables"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String)
    agent_id: Mapped[str] = mapped_column(String)
    name: Mapped[str] = mapped_column(String)
    type: Mapped[str] = mapped_column(String)
    description: Mapped[str] = mapped_column(String)
    choices: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    position: Mapped[int] = mapped_column(Integer, default=0)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CallAnalysis(Base):
    __tablename__ = "call_analyses"

    call_id: Mapped[str] = mapped_column(String, primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, default="pending")
    skip_reason: Mapped[str | None] = mapped_column(String)
    error: Mapped[str | None] = mapped_column(String)
    model: Mapped[str | None] = mapped_column(String)
    variable_snapshot: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    raw_cost_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6), default=Decimal(0))
    charge_txn_id: Mapped[str | None] = mapped_column(String)
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    analyzed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
