"""Signed recording links (006)."""

from __future__ import annotations

from app.core.feature import Feature
from app.recordings.router import router

FEATURE = Feature("recordings", routers=(router,))
