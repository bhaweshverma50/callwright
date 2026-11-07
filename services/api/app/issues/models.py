"""Issue rows (009 T007; data-model.md). Tables come from migration s009_0001.

As elsewhere, ORM mappings declare no foreign keys; the migration owns the constraints.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import Boolean, DateTime, Integer, Numeric, String, Uuid, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.llms.embeddings.base import DIMENSIONS


class Issue(Base):
    __tablename__ = "issues"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String)
    agent_id: Mapped[str] = mapped_column(String)
    agent_type: Mapped[str] = mapped_column(String)
    title: Mapped[str] = mapped_column(String)
    description: Mapped[str] = mapped_column(String, default="")
    suspected_cause: Mapped[str | None] = mapped_column(String)
    evaluator_id: Mapped[str] = mapped_column(String)
    evaluator_name: Mapped[str] = mapped_column(String)
    evaluator_display_name: Mapped[str] = mapped_column(String)
    evaluator_version: Mapped[int] = mapped_column(Integer)
    flow_node_id: Mapped[str | None] = mapped_column(String)
    flow_node_label: Mapped[str | None] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, default="open")
    origin: Mapped[str] = mapped_column(String, default="real")
    affected_call_count: Mapped[int] = mapped_column(Integer, default=0)
    current_version_call_count: Mapped[int] = mapped_column(Integer, default=0)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    centroid: Mapped[list[float] | None] = mapped_column(Vector(DIMENSIONS))
    window_days: Mapped[int] = mapped_column(Integer, default=14)
    current_fix_revision: Mapped[int | None] = mapped_column(Integer)
    calibration_warning: Mapped[bool] = mapped_column(Boolean, default=False)
    recurrence_of: Mapped[str | None] = mapped_column(String)
    applied_agent_version_id: Mapped[str | None] = mapped_column(String)
    applied_fix_revision: Mapped[int | None] = mapped_column(Integer)
    applied_tool_copies: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    applied_by: Mapped[str | None] = mapped_column(String)
    dismiss_reason: Mapped[str | None] = mapped_column(String)
    dismiss_note: Mapped[str | None] = mapped_column(String)
    duplicate_of: Mapped[str | None] = mapped_column(String)
    dismissed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dismissed_by: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class IssueSample(Base):
    __tablename__ = "issue_samples"

    issue_id: Mapped[str] = mapped_column(String, primary_key=True)
    call_id: Mapped[str] = mapped_column(String, primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String)
    evaluator_result_ids: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    reason_excerpt: Mapped[str] = mapped_column(String, default="")
    agent_version_id: Mapped[str | None] = mapped_column(String)
    call_origin: Mapped[str] = mapped_column(String)
    base_call_id: Mapped[str | None] = mapped_column(String)
    failed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class IssueFailureEmbedding(Base):
    __tablename__ = "issue_failure_embeddings"

    evaluator_result_id: Mapped[str] = mapped_column(String, primary_key=True)
    node_key: Mapped[str] = mapped_column(String, primary_key=True, default="")
    workspace_id: Mapped[str] = mapped_column(String)
    embedding_model: Mapped[str] = mapped_column(String)
    source_sha256: Mapped[str] = mapped_column(String)
    embedding: Mapped[list[float]] = mapped_column(Vector(DIMENSIONS))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class IssueFix(Base):
    __tablename__ = "issue_fixes"

    issue_id: Mapped[str] = mapped_column(String, primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String)
    kind: Mapped[str] = mapped_column(String)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    rationale: Mapped[str] = mapped_column(String, default="")
    source: Mapped[str] = mapped_column(String)
    guidance: Mapped[str | None] = mapped_column(String)
    base_agent_version_id: Mapped[str] = mapped_column(String)
    base_config_hash: Mapped[str] = mapped_column(String)
    variant_config_hash: Mapped[str | None] = mapped_column(String)
    variant_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    diff: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    status: Mapped[str] = mapped_column(String, default="draft")
    cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    created_by: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class IssueValidation(Base):
    __tablename__ = "issue_validations"

    issue_id: Mapped[str] = mapped_column(String, primary_key=True)
    attempt: Mapped[int] = mapped_column(Integer, primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String)
    fix_revision: Mapped[int] = mapped_column(Integer)
    auto: Mapped[bool] = mapped_column(Boolean, default=False)
    mode: Mapped[str] = mapped_column(String)
    min_improvement_pp: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    max_regression_pp: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    min_sample: Mapped[int] = mapped_column(Integer)
    base_agent_version_id: Mapped[str] = mapped_column(String)
    base_config_hash: Mapped[str] = mapped_column(String)
    variant_config_hash: Mapped[str] = mapped_column(String)
    affected_call_ids: Mapped[list[str]] = mapped_column(ARRAY(String))
    guard_call_ids: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    control_experiment_id: Mapped[str] = mapped_column(String)
    treatment_experiment_id: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, default="running")
    decision: Mapped[str | None] = mapped_column(String)
    reasons: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    headline: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    evaluator_results: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    treatment_runs_total: Mapped[int] = mapped_column(Integer, default=0)
    treatment_runs_failed: Mapped[int] = mapped_column(Integer, default=0)
    estimated_cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    error_message: Mapped[str | None] = mapped_column(String)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class IssueDetectionRun(Base):
    __tablename__ = "issue_detection_runs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[str] = mapped_column(String)
    agent_id: Mapped[str] = mapped_column(String)
    window_days: Mapped[int] = mapped_column(Integer)
    include_simulated: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String, default="running")
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    calls_scanned: Mapped[int] = mapped_column(Integer, default=0)
    failures_scanned: Mapped[int] = mapped_column(Integer, default=0)
    issues_created: Mapped[int] = mapped_column(Integer, default=0)
    issues_updated: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    error_message: Mapped[str | None] = mapped_column(String)
    created_by: Mapped[str | None] = mapped_column(String)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
