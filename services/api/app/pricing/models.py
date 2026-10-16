"""Versioned pricing catalog tables (global, read-only for the app role)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import BigInteger, DateTime, ForeignKey, Identity, Integer, Numeric, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class CatalogVersion(Base):
    __tablename__ = "pricing_catalog_versions"

    version: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), unique=True)
    notes: Mapped[str | None] = mapped_column(String)
    published_by: Mapped[str | None] = mapped_column(String, ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PricingRate(Base):
    __tablename__ = "pricing_rates"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, ForeignKey("pricing_catalog_versions.version"))
    component: Mapped[str] = mapped_column(String)
    provider: Mapped[str] = mapped_column(String)
    model: Mapped[str | None] = mapped_column(String)
    label: Mapped[str] = mapped_column(String)
    rate_per_min_usd: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    unit: Mapped[str] = mapped_column(String, default="minute")
    bundles: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
