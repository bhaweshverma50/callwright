"""Sign-up, sign-in and sessions (001)."""

from __future__ import annotations

from app.auth.router import router
from app.core.feature import Feature

FEATURE = Feature("auth", routers=(router,))
