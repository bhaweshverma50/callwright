"""Account deletion: schedule and cancel routes, and the hourly erase job."""

from __future__ import annotations

from arq import cron

from app.account.erase import erase_due_accounts
from app.account.router import router
from app.core.feature import Feature

FEATURE = Feature(
    "account",
    routers=(router,),
    jobs={"erase_due_accounts": erase_due_accounts},
    job_timeouts={"erase_due_accounts": 900},
    crons=(cron(erase_due_accounts, minute={17}, run_at_startup=False, unique=True),),
)
