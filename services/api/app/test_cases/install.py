"""Test cases (008)."""

from __future__ import annotations

from app.core.feature import Feature
from app.test_cases.router import router

FEATURE = Feature("test_cases", routers=(router,), id_prefixes=frozenset({"tc"}))
