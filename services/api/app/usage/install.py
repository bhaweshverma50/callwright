"""Usage reports (001)."""

from __future__ import annotations

from app.core.feature import Feature
from app.usage.router import router

FEATURE = Feature("usage", routers=(router,))
