"""Test runs and results (008 T026; data-model.md). Tables from s008_0001.

``TestResult.effective_status`` is a generated column: ``coalesce(override_status,
judge_status)``. ``state`` tracks the result's progress (pending, running, judging, done,
cancelled); the contract's ``status`` is the effective status.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Computed, DateTime, Integer, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class TestRun(Base):
    __tablename__ = "test_runs"
    __test__ = False

    id: Mapped[str] = mapped_column(String, primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String)
    agent_id: Mapped[str] = mapped_column(String)
    number: Mapped[int] = mapped_column(Integer)
    target_type: Mapped[str] = mapped_column(String)
    agent_version_id: Mapped[str | None] = mapped_column(String)
    config_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB)
    config_hash: Mapped[str] = mapped_column(String)
    agent_model: Mapped[str] = mapped_column(String)
    judge_model: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, default="queued")
    total: Mapped[int] = mapped_column(Integer, default=0)
    passed: Mapped[int] = mapped_column(Integer, default=0)
    failed: Mapped[int] = mapped_column(Integer, default=0)
    errored: Mapped[int] = mapped_column(Integer, default=0)
    usage: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    error_message: Mapped[str | None] = mapped_column(String)
    created_by: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TestResult(Base):
    __tablename__ = "test_results"
    __test__ = False

    test_run_id: Mapped[str] = mapped_column(String, primary_key=True)
    test_case_id: Mapped[str] = mapped_column(String, primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String)
    position: Mapped[int] = mapped_column(Integer, default=0)
    case_name: Mapped[str] = mapped_column(String)
    category_slug: Mapped[str] = mapped_column(String)
    user_prompt: Mapped[str] = mapped_column(String)
    expected_behaviour: Mapped[str] = mapped_column(String)
    dynamic_variables: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    state: Mapped[str] = mapped_column(String, default="pending")
    agent_response: Mapped[str | None] = mapped_column(String)
    tool_calls: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    nodes_visited: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    judge_status: Mapped[str | None] = mapped_column(String)
    judge_reasoning: Mapped[str | None] = mapped_column(String)
    judge_model: Mapped[str | None] = mapped_column(String)
    override_status: Mapped[str | None] = mapped_column(String)
    override_note: Mapped[str | None] = mapped_column(String)
    overridden_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    effective_status: Mapped[str | None] = mapped_column(
        String, Computed("coalesce(override_status, judge_status)", persisted=True)
    )
    error_message: Mapped[str | None] = mapped_column(String)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    usage: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
