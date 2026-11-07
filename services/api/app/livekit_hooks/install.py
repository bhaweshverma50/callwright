"""LiveKit webhooks (003)."""

from __future__ import annotations

from app.core.feature import Feature
from app.livekit_hooks.router import router

FEATURE = Feature("livekit_hooks", routers=(router,))
