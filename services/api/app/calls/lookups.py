"""Lookups other features need about a call: its workspace, the configuration it ran and the
workspace's concurrent-call slots."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Mapping
from typing import Any

from callwright_contract.calls import ACTIVE_STATUSES
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.calls.models import Call
from app.calls.origins import SLOT_ORIGINS
from app.calls.ports import AgentSnapshot, registry
from app.core.db import Database
from app.core.errors import not_found
from app.core.ids import is_valid_id
from app.workspaces.models import Workspace

# Versions are immutable, so a cached snapshot never goes stale.
_SNAPSHOTS: OrderedDict[str, AgentSnapshot] = OrderedDict()
_CACHE_SIZE = 1024


async def snapshot_for(session: AsyncSession, version_id: str | None) -> AgentSnapshot | None:
    if version_id is None:
        return None
    cached = _SNAPSHOTS.get(version_id)
    if cached is not None:
        _SNAPSHOTS.move_to_end(version_id)
        return cached
    snapshot = await registry.agent_versions.get_snapshot(session, version_id)
    if snapshot is None:
        return None
    _SNAPSHOTS[version_id] = snapshot
    if len(_SNAPSHOTS) > _CACHE_SIZE:
        _SNAPSHOTS.popitem(last=False)
    return snapshot


async def config_for(session: AsyncSession, call: Call) -> Mapping[str, Any] | None:
    """The configuration ``call`` ran: its agent version, or for a simulated call the exact
    snapshot its simulation run used (008, variants included)."""
    if call.simulation_run_id and registry.run_snapshot is not None:
        run_config = await registry.run_snapshot(session, call.simulation_run_id)
        if run_config is not None:
            return run_config
    snapshot = await snapshot_for(session, call.agent_version_id)
    return snapshot.config if snapshot is not None else None


async def workspace_for_call(db: Database, call_id: str) -> str:
    """The call's workspace from the call row (security-definer lookup), never from a request (R19)."""
    if not is_valid_id(call_id, "call"):
        raise not_found("call")
    async with db.transaction() as session:
        workspace_id = (
            await session.execute(text("select calls_workspace_for(:id)"), {"id": call_id})
        ).scalar()
    if workspace_id is None:
        raise not_found("call")
    return str(workspace_id)


async def concurrency_full(session: AsyncSession, workspace_id: str) -> bool:
    """Whether the workspace's calls on air already fill its concurrent-call limit."""
    limit = (
        await session.execute(select(Workspace.concurrency_limit).where(Workspace.id == workspace_id))
    ).scalar_one()
    active = (
        await session.execute(
            select(func.count())
            .select_from(Call)
            .where(
                Call.workspace_id == workspace_id,
                Call.status.in_(tuple(ACTIVE_STATUSES)),
                Call.origin.in_(SLOT_ORIGINS),
            )
        )
    ).scalar_one()
    return int(active) >= int(limit)


async def _call_where(db: Database, sql: str, value: str) -> tuple[str, str] | None:
    async with db.transaction() as session:
        row = (await session.execute(text(sql), {"v": value})).first()
    return (str(row.call_id), str(row.workspace_id)) if row is not None else None


async def call_for_room(db: Database, room: str) -> tuple[str, str] | None:
    """``(call_id, workspace_id)`` of the call in LiveKit room ``room``."""
    return await _call_where(db, "select call_id, workspace_id from calls_for_room(:v)", room)


async def call_for_egress(db: Database, egress_id: str) -> tuple[str, str] | None:
    """``(call_id, workspace_id)`` of the call recorded by egress ``egress_id``."""
    return await _call_where(db, "select call_id, workspace_id from calls_for_egress(:v)", egress_id)
