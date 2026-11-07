"""003's ``AgentVersionsPort`` over 002's agents service and version reads (wave 2 integration).

The voice runtime codes against ``app.calls.ports.AgentVersionsPort``; the calls feature's
``install`` registers ``AgentVersionsAdapter`` with ``ports.set_agent_versions``. Every method
runs in the caller's workspace-scoped session, so RLS hides other workspaces' agents and versions.

002's ``AgentSnapshot`` carries version bookkeeping (number, schema version, hash, source) that
003 does not need; the adapter keeps the ids and the config and reads ``agent_type`` from the
config's ``type``.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents import service, versions
from app.agents.models import Agent
from app.calls import ports
from app.core.errors import ProblemError


def to_runtime(snapshot: versions.AgentSnapshot, agent_type: str | None = None) -> ports.AgentSnapshot:
    config = snapshot.config
    return ports.AgentSnapshot(
        version_id=snapshot.version_id,
        agent_id=snapshot.agent_id,
        workspace_id=snapshot.workspace_id,
        agent_type=str(config.get("type") or agent_type or "single_prompt"),
        config=config,
        version_number=snapshot.version_number,
    )


class AgentVersionsAdapter:
    """``AgentVersionsPort`` backed by ``agents.service`` and ``agents.versions``."""

    async def _agent(self, session: AsyncSession, agent_id: str) -> Agent | None:
        agent = await session.get(Agent, agent_id)
        return agent if agent is not None and agent.deleted_at is None else None

    async def _snapshot(self, session: AsyncSession, version_id: str) -> ports.AgentSnapshot | None:
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

    async def get_snapshot(self, session: AsyncSession, version_id: str) -> ports.AgentSnapshot | None:
        return await self._snapshot(session, version_id)

    async def snapshot_for_test(self, session: AsyncSession, agent_id: str) -> ports.AgentSnapshot | None:
        try:
            version = await service.snapshot_for_test(session, agent_id)
        except ProblemError as exc:
            if exc.status == 404:
                return None
            raise
        return await self._snapshot(session, version.id)

    async def get_published(self, session: AsyncSession, agent_id: str) -> ports.AgentSnapshot | None:
        version = await versions.get_published(session, agent_id)
        return await self._snapshot(session, version.id) if version is not None else None
