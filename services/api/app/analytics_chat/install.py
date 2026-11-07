"""Analytics assistant (006)."""

from __future__ import annotations

from arq import cron

from app.analytics_chat.jobs import purge_analytics_audit
from app.analytics_chat.router import router
from app.core.feature import Feature

FEATURE = Feature(
    "analytics_chat",
    routers=(router,),
    jobs={"purge_analytics_audit": purge_analytics_audit},
    crons=(cron(purge_analytics_audit, hour={4}, minute={30}, run_at_startup=False),),
)
