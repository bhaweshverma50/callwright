"""Per-agent evaluator settings, runs, run groups, result items and call embeddings (007 T035)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    Identity,
    Integer,
    Numeric,
    SmallInteger,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class AgentEvalSetting(Base):
    __tablename__ = "agent_eval_settings"

    agent_id: Mapped[str] = mapped_column(String, primary_key=True)
    evaluator_id: Mapped[str] = mapped_column(String, primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String)
    enabled: Mapped[bool] = mapped_column(Boolean)
    overrides: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    is_headline: Mapped[bool] = mapped_column(Boolean, default=False)
    headline_position: Mapped[int | None] = mapped_column(SmallInteger)
    updated_by: Mapped[str | None] = mapped_column(String)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class EvaluatorRunGroup(Base):
    __tablename__ = "evaluator_run_groups"

    run_group_id: Mapped[str] = mapped_column(String, primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String)
    call_id: Mapped[str] = mapped_column(String)
    trigger: Mapped[str] = mapped_column(String)
    idempotency_key: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, default="active")
    created_by: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class EvaluatorRun(Base):
    __tablename__ = "evaluator_runs"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String)
    call_id: Mapped[str] = mapped_column(String)
    agent_id: Mapped[str] = mapped_column(String)
    evaluator_id: Mapped[str] = mapped_column(String)
    evaluator_version: Mapped[int] = mapped_column(Integer)
    run_group_id: Mapped[str] = mapped_column(String)
    trigger: Mapped[str] = mapped_column(String)
    settings_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    settings_hash: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, default="pending")
    skip_reason: Mapped[str | None] = mapped_column(String)
    error: Mapped[str | None] = mapped_column(String)
    verdict: Mapped[str | None] = mapped_column(String)
    score: Mapped[float | None] = mapped_column(Float)
    rationale: Mapped[str | None] = mapped_column(String)
    judge_model: Mapped[str | None] = mapped_column(String)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    raw_cost_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6), default=Decimal(0))
    charge_txn_id: Mapped[str | None] = mapped_column(String)
    attempt: Mapped[int] = mapped_column(SmallInteger, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class EvaluatorResultItem(Base):
    __tablename__ = "evaluator_result_items"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String)
    run_id: Mapped[str] = mapped_column(String)
    position: Mapped[int] = mapped_column(Integer, default=0)
    turn_index: Mapped[int | None] = mapped_column(Integer)
    flow_node_id: Mapped[str | None] = mapped_column(String)
    flow_node_label: Mapped[str | None] = mapped_column(String)
    start_ms: Mapped[int | None] = mapped_column(Integer)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    verdict: Mapped[str] = mapped_column(String)
    score: Mapped[float | None] = mapped_column(Float)
    rationale: Mapped[str] = mapped_column(String, default="")
    evidence: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
