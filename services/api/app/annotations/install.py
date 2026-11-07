"""Call annotations (007)."""

from __future__ import annotations

from app.annotations.router import router
from app.core.feature import Feature

FEATURE = Feature("annotations", routers=(router,), id_prefixes=frozenset({"ann"}))
