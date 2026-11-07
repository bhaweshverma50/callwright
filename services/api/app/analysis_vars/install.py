"""Post-call analysis variables (007)."""

from __future__ import annotations

from app.analysis_vars.jobs import RERUN_ANALYSIS, rerun_analysis
from app.analysis_vars.router import router
from app.core.feature import Feature

FEATURE = Feature(
    "analysis_vars", routers=(router,), jobs={RERUN_ANALYSIS: rerun_analysis}, id_prefixes=frozenset({"var"})
)
