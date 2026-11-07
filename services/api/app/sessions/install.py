"""Web test calls (003)."""

from __future__ import annotations

from app.core.feature import Feature
from app.sessions.router import router

FEATURE = Feature("sessions", routers=(router,))
