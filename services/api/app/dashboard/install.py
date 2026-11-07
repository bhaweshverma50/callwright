"""Dashboard (006)."""

from __future__ import annotations

from app.core.feature import Feature
from app.dashboard.router import router

FEATURE = Feature("dashboard", routers=(router,))
