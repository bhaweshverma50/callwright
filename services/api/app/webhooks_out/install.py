"""Outbound customer webhooks (003)."""

from __future__ import annotations

from arq import cron

from app.core.feature import Feature
from app.webhooks_out.jobs import deliver_webhook, purge_webhook_deliveries
from app.webhooks_out.router import router
from app.webhooks_out.service import DELIVER_WEBHOOK

FEATURE = Feature(
    "webhooks_out",
    routers=(router,),
    jobs={DELIVER_WEBHOOK: deliver_webhook, "purge_webhook_deliveries": purge_webhook_deliveries},
    # 003 R16.
    crons=(cron(purge_webhook_deliveries, hour={4}, minute={0}, run_at_startup=False),),
    id_prefixes=frozenset({"whd"}),
)
