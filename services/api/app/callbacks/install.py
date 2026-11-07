"""Scheduled callbacks (011)."""

from __future__ import annotations

from arq import cron

from app.callbacks.jobs import place_due_callbacks
from app.callbacks.router import internal_router, router
from app.core.feature import Feature

FEATURE = Feature(
    "callbacks",
    routers=(router, internal_router),
    jobs={"place_due_callbacks": place_due_callbacks},
    crons=(cron(place_due_callbacks, second={20}, run_at_startup=False, unique=True),),
    id_prefixes=frozenset({"cbk"}),
)
