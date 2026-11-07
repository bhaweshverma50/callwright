"""Homepage playground."""

from __future__ import annotations

from app.core.feature import Feature
from app.demo.router import router

FEATURE = Feature("demo", routers=(router,))
