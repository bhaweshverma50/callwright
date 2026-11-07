"""Credits, top-ups and the ledger (001)."""

from __future__ import annotations

from arq import cron

from app.billing.jobs import reconcile_balances
from app.billing.router import router
from app.core.feature import Feature

FEATURE = Feature(
    "billing",
    routers=(router,),
    jobs={"reconcile_balances": reconcile_balances},
    crons=(cron(reconcile_balances, hour={3}, minute={0}, run_at_startup=False),),
    id_prefixes=frozenset({"txn"}),
)
