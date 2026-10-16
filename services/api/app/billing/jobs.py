"""Nightly ledger reconciliation (T056, SC-003).

For every workspace: ``sum(amount_usd)`` must equal the latest ``balance_after_usd`` and each row
must chain from the previous one (``balance_after = previous + amount``, ``seq`` without gaps).

CLI: ``uv run python -m app.billing.jobs reconcile --now`` prints the result and exits 1 on any
mismatch. The arq worker runs ``reconcile_balances`` daily at 03:00 UTC.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy import text

from app.core.config import get_settings
from app.core.db import Database

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Mismatch:
    workspace_id: str
    sum_usd: Decimal
    balance_usd: Decimal
    chain_breaks: int


@dataclass(frozen=True)
class ReconcileResult:
    workspaces: int
    mismatches: list[Mismatch]


async def reconcile(db: Database) -> ReconcileResult:
    async with db.admin_transaction() as session:
        rows = (await session.execute(text("select * from billing_reconcile()"))).all()
    mismatches = [
        Mismatch(r.workspace_id, Decimal(r.sum_usd), Decimal(r.balance_usd), int(r.chain_breaks))
        for r in rows
        if Decimal(r.sum_usd) != Decimal(r.balance_usd) or int(r.chain_breaks) > 0
    ]
    for m in mismatches:
        logger.error(
            "ledger mismatch workspace=%s sum=%s balance=%s chain_breaks=%s",
            m.workspace_id,
            m.sum_usd,
            m.balance_usd,
            m.chain_breaks,
        )
    return ReconcileResult(workspaces=len(rows), mismatches=mismatches)


async def reconcile_balances(ctx: dict[str, Any]) -> dict[str, int]:
    """arq job."""
    result = await reconcile(ctx["db"])
    return {"workspaces": result.workspaces, "mismatches": len(result.mismatches)}


async def _main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.billing.jobs")
    parser.add_argument("command", choices=["reconcile"])
    parser.add_argument("--now", action="store_true", help="run immediately (the only mode)")
    parser.parse_args(argv)
    settings = get_settings()
    db = Database(settings.database_url, settings.database_admin_url, pool_size=1)
    try:
        result = await reconcile(db)
    finally:
        await db.dispose()
    print(f"workspaces checked: {result.workspaces}; mismatches: {len(result.mismatches)}")
    for m in result.mismatches:
        print(f"  {m.workspace_id}: sum {m.sum_usd} balance {m.balance_usd} chain breaks {m.chain_breaks}")
    return 1 if result.mismatches else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_main(sys.argv[1:])))
