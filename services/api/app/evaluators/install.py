"""Evaluator catalog (007)."""

from __future__ import annotations

from app.core.feature import Feature
from app.evaluators.router import router

FEATURE = Feature("evaluators", routers=(router,), id_prefixes=frozenset({"evl"}))
