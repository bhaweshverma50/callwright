"""Read-only executor for compiled metric queries (006 T065, research R4).

Each query runs in its own transaction that is read only, scoped to the workspace, switched to
``cw_analytics_reader`` (which can read the ``analytics`` views and nothing else) and bounded by a
3 s statement timeout. Rows come back as JSON-ready dicts, at most ``limit``; ``truncated`` says
whether more matched.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Select, text

from app.core.db import Database

STATEMENT_TIMEOUT = "3s"


def _plain(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(round(value, 6))
    if isinstance(value, float):
        return round(value, 6)
    if isinstance(value, datetime | date):
        return value.isoformat()
    return value


async def run_query(
    db: Database, workspace_id: str, stmt: Select[Any], limit: int
) -> tuple[list[dict[str, Any]], bool]:
    async with db.engine.connect() as conn, conn.begin():
        await conn.execute(text("SET TRANSACTION READ ONLY"))
        await conn.execute(text("select set_config('app.workspace_id', :ws, true)"), {"ws": workspace_id})
        await conn.execute(text("SET LOCAL ROLE cw_analytics_reader"))
        await conn.execute(text(f"SET LOCAL statement_timeout = '{STATEMENT_TIMEOUT}'"))
        rows = (await conn.execute(stmt)).mappings().all()
    out = [{k: _plain(v) for k, v in r.items()} for r in rows[:limit]]
    return out, len(rows) > limit
