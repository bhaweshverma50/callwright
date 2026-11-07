"""Workspaces and members (001)."""

from __future__ import annotations

from app.core.feature import Feature
from app.workspaces.router import router

FEATURE = Feature("workspaces", routers=(router,), id_prefixes=frozenset({"ws", "usr"}))
