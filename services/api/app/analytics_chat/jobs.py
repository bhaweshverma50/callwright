"""Daily purge of assistant and voice copilot audit rows older than 30 days (006 T069, T079)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import text

from app.core.db import Database

RETENTION_DAYS = 30


async def purge_analytics_audit(ctx: dict[str, Any]) -> int:
    db: Database = ctx["db"]
    async with db.transaction() as session:
        return int(
            (
                await session.execute(text("select analytics_audit_purge(:d)"), {"d": RETENTION_DAYS})
            ).scalar_one()
        )
