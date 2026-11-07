"""Model catalog (002)."""

from __future__ import annotations

from app.core.feature import Feature
from app.llms.router import router

FEATURE = Feature("llms", routers=(router,))
