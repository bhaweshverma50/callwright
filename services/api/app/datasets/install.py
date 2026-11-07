"""Datasets (008)."""

from __future__ import annotations

from app.core.feature import Feature
from app.datasets.router import router

FEATURE = Feature("datasets", routers=(router,), id_prefixes=frozenset({"ds"}))
