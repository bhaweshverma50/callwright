"""Voice catalog and ambience uploads (002)."""

from __future__ import annotations

from app.core.feature import Feature
from app.voices.router import router

FEATURE = Feature("voices", routers=(router,))
