"""Agent version reads: snapshots, history, diffs (T022, T059, T086; research R2, R3, R13).

Every function takes an ``AsyncSession`` already scoped to the workspace by
``Database.transaction(workspace_id=...)`` (RLS). Versions are written only by
``agents.service`` (the save pipeline).

Interfaces for other features (in-process):

* ``get_snapshot(session, version_id) -> AgentSnapshot``: the frozen AgentConfig a call runs
  with (003 admission and claim, 006 call detail, 008). Works for deleted agents. ``config`` is
  upcast to the current format and includes the snapshot-only ``tools`` and ``knowledge``
  blocks when resolvers wrote them.
* ``get(session, version_id) -> AgentVersion | None``: the row itself.
* ``get_published(session, agent_id) -> AgentVersion | None``: the version live channels use
  (003 admission, 010 routing); ``None`` when unpublished or the agent is deleted.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent_versions.diff import diff_configs
from app.agent_versions.models import AgentVersion
from app.agents.defaults import CURRENT_SCHEMA_VERSION
from app.agents.hooks import SNAPSHOT_ONLY_BLOCKS
from app.agents.models import Agent
from app.agents.schemas import upcast
from app.core.errors import not_found
from app.core.pagination import page_window


class VersionNotFound(LookupError):
    pass


@dataclass(frozen=True)
class AgentSnapshot:
    """The frozen configuration of one version (what a call runs with)."""

    version_id: str
    agent_id: str
    workspace_id: str
    version_number: int
    schema_version: int
    content_hash: str
    source: str
    config: dict[str, Any]


def draft_part(config: Mapping[str, Any]) -> dict[str, Any]:
    """A version config without the snapshot-only blocks (what a draft holds)."""
    return {k: copy.deepcopy(v) for k, v in config.items() if k not in SNAPSHOT_ONLY_BLOCKS}


def summary_of(config: Mapping[str, Any]) -> dict[str, Any]:
    """At-a-glance contents for the history list (data-model section 2)."""
    llm = config.get("llm") or {}
    tts = config.get("tts") or {}
    flow = config.get("flow")
    node_count = None
    if config.get("type") == "flow":
        graph = flow.get("graph") if isinstance(flow, Mapping) else None
        nodes = graph.get("nodes") if isinstance(graph, Mapping) else None
        node_count = len(nodes) if isinstance(nodes, list) else 0
    return {
        "llm_model": str(llm.get("model") or ""),
        "tts_provider": str(tts.get("provider") or ""),
        "tts_voice_id": str(tts.get("voice_id") or ""),
        "tool_count": len(config.get("tool_ids") or []),
        "kb_count": len(config.get("kb_ids") or []),
        "node_count": node_count,
    }


async def get(session: AsyncSession, version_id: str) -> AgentVersion | None:
    return await session.get(AgentVersion, version_id)


async def get_snapshot(session: AsyncSession, version_id: str) -> AgentSnapshot:
    """The frozen AgentConfig of ``version_id`` (raises ``VersionNotFound``)."""
    version = await session.get(AgentVersion, version_id)
    if version is None:
        raise VersionNotFound(version_id)
    return AgentSnapshot(
        version_id=version.id,
        agent_id=version.agent_id,
        workspace_id=version.workspace_id,
        version_number=version.version_number,
        schema_version=CURRENT_SCHEMA_VERSION,
        content_hash=version.content_hash,
        source=version.source,
        config=upcast(version.config),
    )


async def get_published(session: AsyncSession, agent_id: str) -> AgentVersion | None:
    agent = await session.get(Agent, agent_id)
    if agent is None or agent.deleted_at is not None or agent.pinned_version_id is None:
        return None
    return await session.get(AgentVersion, agent.pinned_version_id)


async def get_for_agent(session: AsyncSession, agent_id: str, version_id: str) -> AgentVersion:
    version = await session.get(AgentVersion, version_id)
    if version is None or version.agent_id != agent_id:
        raise not_found("version")
    return version


async def find_by_hash(session: AsyncSession, agent_id: str, digest: str) -> AgentVersion | None:
    return (
        await session.execute(
            select(AgentVersion)
            .where(AgentVersion.agent_id == agent_id, AgentVersion.content_hash == digest)
            .order_by(AgentVersion.version_number.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def list_versions(
    session: AsyncSession, agent_id: str, *, page: int, page_size: int, include_test: bool = False
) -> tuple[list[AgentVersion], int]:
    where = [AgentVersion.agent_id == agent_id]
    if not include_test:
        where.append(AgentVersion.source != "test")
    total = int(
        (await session.execute(select(func.count()).select_from(AgentVersion).where(*where))).scalar_one()
    )
    rows = (
        await session.execute(
            select(AgentVersion)
            .where(*where)
            .order_by(AgentVersion.version_number.desc())
            .slice(*page_window(page, page_size))
        )
    ).scalars()
    return list(rows), total


async def numbers_for(session: AsyncSession, version_ids: set[str]) -> dict[str, int]:
    if not version_ids:
        return {}
    rows = await session.execute(
        select(AgentVersion.id, AgentVersion.version_number).where(AgentVersion.id.in_(version_ids))
    )
    return {row.id: int(row.version_number) for row in rows}


async def diff(session: AsyncSession, agent: Agent, version_id: str, against: str) -> dict[str, Any]:
    """Changes from ``against`` (a version id or ``draft``) to ``version_id``."""
    target = await get_for_agent(session, agent.id, version_id)
    new = upcast(target.config)
    if against == "draft":
        old: dict[str, Any] = upcast(agent.draft_config)
        new = draft_part(new)
    else:
        base = await get_for_agent(session, agent.id, against)
        old = upcast(base.config)
    return {"from": against, "to": target.id, "changes": diff_configs(old, new)}
