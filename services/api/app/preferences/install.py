"""User preferences (013)."""

from __future__ import annotations

from app.core.feature import Feature
from app.preferences.router import router

FEATURE = Feature("preferences", routers=(router,))
