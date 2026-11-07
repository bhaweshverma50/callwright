"""Price catalog and quotes (001)."""

from __future__ import annotations

from app.core.feature import Feature
from app.pricing.router import router

FEATURE = Feature("pricing", routers=(router,))
