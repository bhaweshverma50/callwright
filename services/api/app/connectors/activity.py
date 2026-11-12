"""Who-did-what for connections and sources (022 FR-025, research R14). Append-only: the app
role can insert and read ``connector_activity`` but never change or delete it."""

from __future__ import annotations

from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.connectors.models import ConnectorActivity

Action = Literal[
    "connection_added",
    "connection_reconnected",
    "connection_removed",
    "source_added",
    "source_removed",
    "held_archive_confirmed",
    "held_archive_cancelled",
]


async def record(
    session: AsyncSession,
    *,
    workspace_id: str,
    action: Action,
    subject_type: Literal["connection", "source"],
    subject_id: str,
    actor_user_id: str | None,
    detail: dict[str, Any] | None = None,
) -> None:
    session.add(
        ConnectorActivity(
            workspace_id=workspace_id,
            actor_user_id=actor_user_id,
            action=action,
            subject_type=subject_type,
            subject_id=subject_id,
            detail=detail or {},
        )
    )
    await session.flush()


async def recent(session: AsyncSession, subject_ids: list[str], limit: int = 50) -> list[ConnectorActivity]:
    rows = await session.execute(
        select(ConnectorActivity)
        .where(ConnectorActivity.subject_id.in_(subject_ids))
        .order_by(ConnectorActivity.created_at.desc(), ConnectorActivity.id.desc())
        .limit(limit)
    )
    return list(rows.scalars())
