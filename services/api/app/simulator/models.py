"""Simulation batches (experiments) and runs (008 T047; data-model.md). Tables from s008_0001.

A batch stores its configuration snapshot once; its runs keep only the hash
(``config_snapshot`` is null on batch runs and read from the batch).
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import DateTime, Integer, Numeric, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class SimulationExperiment(Base):
    __tablename__ = "simulation_experiments"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String)
    agent_id: Mapped[str] = mapped_column(String)
    name: Mapped[str] = mapped_column(String)
    mode: Mapped[str] = mapped_column(String)
    target_type: Mapped[str] = mapped_column(String)
    agent_version_id: Mapped[str | None] = mapped_column(String)
    variant_label: Mapped[str | None] = mapped_column(String)
    config_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB)
    config_hash: Mapped[str] = mapped_column(String)
    variant_diff: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    source: Mapped[str] = mapped_column(String)
    dataset_id: Mapped[str | None] = mapped_column(String)
    issue_id: Mapped[str | None] = mapped_column(String)
    settings: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    status: Mapped[str] = mapped_column(String, default="pending")
    total_count: Mapped[int] = mapped_column(Integer, default=0)
    completed_count: Mapped[int] = mapped_column(Integer, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, default=0)
    cancelled_count: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    error_message: Mapped[str | None] = mapped_column(String)
    hooks_fired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SimulationRun(Base):
    __tablename__ = "simulation_runs"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String)
    agent_id: Mapped[str] = mapped_column(String)
    experiment_id: Mapped[str | None] = mapped_column(String)
    base_call_id: Mapped[str | None] = mapped_column(String)
    mode: Mapped[str] = mapped_column(String)
    target_type: Mapped[str] = mapped_column(String)
    agent_version_id: Mapped[str | None] = mapped_column(String)
    variant_label: Mapped[str | None] = mapped_column(String)
    config_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    config_hash: Mapped[str] = mapped_column(String)
    persona_brief: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    persona_source: Mapped[str | None] = mapped_column(String)
    dynamic_variables: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    settings: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    status: Mapped[str] = mapped_column(String, default="pending")
    output_call_id: Mapped[str | None] = mapped_column(String)
    end_reason: Mapped[str | None] = mapped_column(String)
    diverged_at_turn: Mapped[int | None] = mapped_column(Integer)
    answer_source_counts: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    usage: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    error_message: Mapped[str | None] = mapped_column(String)
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
