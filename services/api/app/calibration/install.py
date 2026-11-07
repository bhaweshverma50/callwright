"""Judge calibration (007)."""

from __future__ import annotations

from app.calibration.router import router
from app.core.feature import Feature

FEATURE = Feature("calibration", routers=(router,))
