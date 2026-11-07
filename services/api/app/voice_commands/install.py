"""Voice copilot commands (006)."""

from __future__ import annotations

from app.core.feature import Feature
from app.voice_commands.router import router

FEATURE = Feature("voice_commands", routers=(router,))
