"""Outbound calls, calling hours and the do-not-call list (010)."""

from __future__ import annotations

from app.core.feature import Feature
from app.outbound.router import router

FEATURE = Feature("outbound", routers=(router,), id_prefixes=frozenset({"dnc"}))
