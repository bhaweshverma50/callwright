"""Agents (002)."""

from __future__ import annotations

from app.agents.router import router
from app.core.feature import Feature

FEATURE = Feature("agents", routers=(router,), id_prefixes=frozenset({"agt"}))
