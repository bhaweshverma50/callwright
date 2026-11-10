"""The agent versions calls admit and run, read through 002's agents service.

Every method runs in the caller's workspace-scoped session, so RLS hides other workspaces' agents
and versions. ``get_snapshot(version_id)`` returns the frozen config of one version;
``snapshot_for_test(agent_id)`` the version for the current draft (created with ``source = test``
when the draft changed, never published); ``get_published(agent_id)`` the pinned version or None.

002's snapshot carries version bookkeeping (schema version, hash, source) that calls do not need;
``AgentSnapshot`` keeps the ids and the config and reads ``agent_type`` from the config's ``type``.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents import service, versions
from app.agents.models import Agent
from app.core.errors import ProblemError


@dataclass(frozen=True)
class AgentSnapshot:
    """One immutable agent version as 003 needs it."""

    version_id: str
    agent_id: str
    workspace_id: str
    agent_type: str  # single_prompt | flow
    config: Mapping[str, Any]
    version_number: int | None = None


def to_runtime(snapshot: versions.AgentSnapshot, agent_type: str | None = None) -> AgentSnapshot:
    config = snapshot.config
    return AgentSnapshot(
        version_id=snapshot.version_id,
        agent_id=snapshot.agent_id,
        workspace_id=snapshot.workspace_id,
        agent_type=str(config.get("type") or agent_type or "single_prompt"),
        config=config,
        version_number=snapshot.version_number,
    )


class AgentVersionsAdapter:
    """Agent versions read through ``agents.service`` and ``agents.versions``."""

    async def _agent(self, session: AsyncSession, agent_id: str) -> Agent | None:
        agent = await session.get(Agent, agent_id)
        return agent if agent is not None and agent.deleted_at is None else None

    async def _snapshot(self, session: AsyncSession, version_id: str) -> AgentSnapshot | None:
        try:
            snapshot = await versions.get_snapshot(session, version_id)
        except versions.VersionNotFound:
            return None
        agent_type = None
        if not snapshot.config.get("type"):
            agent = await session.get(Agent, snapshot.agent_id)
            agent_type = agent.type if agent is not None else None
        return to_runtime(snapshot, agent_type)

    async def agent_exists(self, session: AsyncSession, agent_id: str) -> bool:
        return await self._agent(session, agent_id) is not None

    async def get_snapshot(self, session: AsyncSession, version_id: str) -> AgentSnapshot | None:
        return await self._snapshot(session, version_id)

    async def snapshot_for_test(self, session: AsyncSession, agent_id: str) -> AgentSnapshot | None:
        try:
            version = await service.snapshot_for_test(session, agent_id)
        except ProblemError as exc:
            if exc.status == 404:
                return None
            raise
        return await self._snapshot(session, version.id)

    async def get_published(self, session: AsyncSession, agent_id: str) -> AgentSnapshot | None:
        version = await versions.get_published(session, agent_id)
        return await self._snapshot(session, version.id) if version is not None else None
