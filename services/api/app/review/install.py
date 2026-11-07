"""Review queue (007)."""

from __future__ import annotations

from app.core.feature import Feature
from app.review.router import router

FEATURE = Feature("review", routers=(router,))
