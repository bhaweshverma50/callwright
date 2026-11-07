"""Agent templates (002)."""

from __future__ import annotations

from app.core.feature import Feature
from app.templates.router import router

FEATURE = Feature("templates", routers=(router,))
