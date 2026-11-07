"""Worker call events (003)."""

from __future__ import annotations

from app.call_events.router import router
from app.core.feature import Feature

FEATURE = Feature("call_events", routers=(router,))
