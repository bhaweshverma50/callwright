"""Prompt assistant (002)."""

from __future__ import annotations

from app.core.feature import Feature
from app.prompt_ai.router import router

FEATURE = Feature("prompt_ai", routers=(router,))
