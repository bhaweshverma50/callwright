"""Evaluator catalog rows and immutable versions (007 T031). Built-ins have no workspace."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class EvaluatorRow(Base):
    __tablename__ = "evaluators"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    workspace_id: Mapped[str | None] = mapped_column(String)
    kind: Mapped[str] = mapped_column(String)
    evaluator_type: Mapped[str] = mapped_column(String)
    name: Mapped[str] = mapped_column(String)
    display_name: Mapped[str] = mapped_column(String)
    description: Mapped[str | None] = mapped_column(String)
    scope: Mapped[str] = mapped_column(String)
    cost_class: Mapped[str] = mapped_column(String)
    output_kind: Mapped[str] = mapped_column(String, default="class")
    agent_types: Mapped[list[str]] = mapped_column(ARRAY(Text))
    settings_schema: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    score_range: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    current_version: Mapped[int] = mapped_column(Integer, default=1)
    enabled_by_default: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[str | None] = mapped_column(String)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class EvaluatorVersion(Base):
    __tablename__ = "evaluator_versions"

    evaluator_id: Mapped[str] = mapped_column(String, primary_key=True)
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    workspace_id: Mapped[str | None] = mapped_column(String)
    definition: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    judge_model: Mapped[str | None] = mapped_column(String)
    created_by: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
