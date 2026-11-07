"""``place_due_callbacks`` cron (011): every minute, dial the callbacks that are due."""

from __future__ import annotations

from typing import Any

from app.callbacks.service import place_due
from app.outbound.service import deps_from


async def place_due_callbacks(ctx: dict[str, Any]) -> int:
    return await place_due(deps_from(ctx))
