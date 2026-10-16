"""Agent versions: record, list, read, diff, publish, unpublish, restore and test snapshots
(T022, T059, T086, T089, T099; research R2, R3, R13).

Every function takes an ``AsyncSession`` already scoped to the workspace by
``Database.transaction(workspace_id=...)`` (RLS), like ``billing.service``.

Interfaces for other features (in-process):

* ``get_snapshot(session, version_id) -> AgentSnapshot``: the frozen AgentConfig a call runs
  with (003 admission and claim, 006 call detail, 008). Works for deleted agents. ``config`` is
  upcast to the current format and includes the snapshot-only ``tools`` and ``knowledge``
  blocks when resolvers wrote them.
* ``get(session, version_id) -> AgentVersion | None``: the row itself.
* ``get_published(session, agent_id) -> AgentVersion | None``: the version live channels use
  (003 admission, 010 routing); ``None`` when unpublished or the agent is deleted.
* ``snapshot_for_test(session, agent_id) -> AgentVersion``: a version matching the current draft
  (including resolved tools); reuses an identical version, else records ``source = test``. Never
  publishes (003 draft test calls, research R18).
* ``create_version(session, agent_id, config, ...)``: record a version from a config (004 flow
  publish), deduplicated by content hash, optionally publishing it.

Version numbers are assigned while the agent row is locked (``SELECT ... FOR UPDATE``).
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from opentelemetry import trace
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent_versions.canonical import content_hash
from app.agent_versions.diff import diff_configs
from app.agent_versions.models import AgentVersion
from app.agents import hooks
from app.agents.checks import validate_config
from app.agents.models import Agent
from app.agents.schemas import CURRENT_SCHEMA_VERSION, upcast
from app.core.errors import ProblemError, not_found, validation_failed
from app.core.ids import new_id

tracer = trace.get_tracer("app.agent_versions")

SOURCES = ("create", "save", "restore", "template", "duplicate", "flow_publish", "test")


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


@dataclass(frozen=True)
class Recorded:
    version: AgentVersion
    created: bool


def publish_blocked(issues: list[dict[str, str]]) -> ProblemError:
    return ProblemError(
        422,
        "publish_blocked",
        "Version cannot be published",
        "Fix the listed problems, save, and publish again.",
        errors=issues,
    )


# Snapshot assembly ---------------------------------------------------------------------------


def draft_part(config: Mapping[str, Any]) -> dict[str, Any]:
    """A version config without the snapshot-only blocks (what a draft holds)."""
    return {k: copy.deepcopy(v) for k, v in config.items() if k not in hooks.SNAPSHOT_ONLY_BLOCKS}


async def resolve_snapshot(
    session: AsyncSession, *, workspace_id: str, agent_id: str, agent_type: str, config: Mapping[str, Any]
) -> dict[str, Any]:
    """Draft config plus the snapshot-only blocks written by registered resolvers (R5, FR-028)."""
    base = draft_part(config)

    def make_context(block: str) -> hooks.HookContext:
        return hooks.HookContext(
            block=block,
            value=base.get(block),
            config=base,
            agent_type=agent_type,
            workspace_id=workspace_id,
            agent_id=agent_id,
            session=session,
        )

    resolved = await hooks.run_snapshot_resolvers(make_context)
    return {**base, **resolved}


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


async def lock_agent(session: AsyncSession, agent_id: str, *, include_deleted: bool = False) -> Agent:
    agent = (
        await session.execute(select(Agent).where(Agent.id == agent_id).with_for_update())
    ).scalar_one_or_none()
    if agent is None or (agent.deleted_at is not None and not include_deleted):
        raise not_found("agent")
    return agent


async def _next_number(session: AsyncSession, agent_id: str) -> int:
    current = (
        await session.execute(
            select(func.max(AgentVersion.version_number)).where(AgentVersion.agent_id == agent_id)
        )
    ).scalar()
    return int(current or 0) + 1


async def find_by_hash(session: AsyncSession, agent_id: str, digest: str) -> AgentVersion | None:
    return (
        await session.execute(
            select(AgentVersion)
            .where(AgentVersion.agent_id == agent_id, AgentVersion.content_hash == digest)
            .order_by(AgentVersion.version_number.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def insert_version(
    session: AsyncSession,
    *,
    workspace_id: str,
    agent_id: str,
    resolved_config: dict[str, Any],
    source: str,
    note: str | None,
    created_by: str | None,
    publish_blockers: list[dict[str, str]],
    parent_version_id: str | None,
    restored_from_version_id: str | None = None,
    version_id: str | None = None,
) -> AgentVersion:
    """Insert one immutable version. The caller holds the agent row lock (or is creating it)."""
    if source not in SOURCES:
        raise ValueError(f"unknown version source {source!r}")
    version = AgentVersion(
        id=version_id or new_id("agv"),
        workspace_id=workspace_id,
        agent_id=agent_id,
        version_number=await _next_number(session, agent_id),
        schema_version=int(resolved_config.get("schema_version", CURRENT_SCHEMA_VERSION)),
        config=resolved_config,
        content_hash=content_hash(resolved_config),
        source=source,
        restored_from_version_id=restored_from_version_id,
        parent_version_id=parent_version_id,
        summary=summary_of(resolved_config),
        note=(note or None),
        publish_blockers=publish_blockers,
        created_by=created_by,
    )
    session.add(version)
    await session.flush()
    return version


# Reads -----------------------------------------------------------------------------------------


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
        content_hash=version.content_hash.strip(),
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
            .offset((page - 1) * page_size)
            .limit(page_size)
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


# Writes ----------------------------------------------------------------------------------------


async def current_blockers(
    session: AsyncSession, agent: Agent, version: AgentVersion, *, allow_http_webhook: bool = False
) -> list[dict[str, str]]:
    """Errors and publish blockers of ``version`` re-evaluated now (catalog, prices, hooks)."""
    result = await validate_config(
        agent.type,
        draft_part(upcast(version.config)),
        agent.id,
        session=session,
        workspace_id=agent.workspace_id,
        allow_http_webhook=allow_http_webhook,
    )
    return result.errors + result.publish_blockers


async def publish(
    session: AsyncSession, agent_id: str, version_id: str, *, allow_http_webhook: bool = False
) -> Agent:
    """Pin ``version_id`` for live channels after re-checking its blockers (FR-026)."""
    with tracer.start_as_current_span("agent_versions.publish"):
        agent = await lock_agent(session, agent_id)
        version = await get_for_agent(session, agent.id, version_id)
        blockers = await current_blockers(session, agent, version, allow_http_webhook=allow_http_webhook)
        if blockers:
            raise publish_blocked(blockers)
        agent.pinned_version_id = version.id
        await session.flush()
        return agent


async def unpublish(session: AsyncSession, agent_id: str) -> Agent:
    agent = await lock_agent(session, agent_id)
    agent.pinned_version_id = None
    await session.flush()
    return agent


@dataclass(frozen=True)
class RestoreOutcome:
    agent: Agent
    version: AgentVersion
    warnings: list[dict[str, str]]
    publish_blockers: list[dict[str, str]]


async def restore(
    session: AsyncSession,
    agent_id: str,
    version_id: str,
    *,
    expected_revision: int | None,
    note: str | None,
    publish_now: bool,
    user_id: str | None,
    allow_http_webhook: bool = False,
) -> RestoreOutcome:
    """Copy a version into the draft as a new ``restore`` version; optionally publish it."""
    with tracer.start_as_current_span("agent_versions.restore"):
        agent = await lock_agent(session, agent_id)
        check_revision(agent, expected_revision)
        source = await get_for_agent(session, agent.id, version_id)
        config = draft_part(upcast(source.config))
        result = await validate_config(
            agent.type,
            config,
            agent.id,
            session=session,
            workspace_id=agent.workspace_id,
            allow_http_webhook=allow_http_webhook,
        )
        if result.errors:
            raise validation_failed(result.errors)
        if publish_now and result.publish_blockers:
            raise publish_blocked(result.publish_blockers)
        normalized = result.normalized_config
        resolved = await resolve_snapshot(
            session,
            workspace_id=agent.workspace_id,
            agent_id=agent.id,
            agent_type=agent.type,
            config=normalized,
        )
        version = await insert_version(
            session,
            workspace_id=agent.workspace_id,
            agent_id=agent.id,
            resolved_config=resolved,
            source="restore",
            note=note or f"Restored from version {source.version_number}",
            created_by=user_id,
            publish_blockers=result.publish_blockers,
            parent_version_id=agent.draft_version_id,
            restored_from_version_id=source.id,
        )
        apply_draft(agent, normalized, version)
        if publish_now:
            agent.pinned_version_id = version.id
        await session.flush()
        return RestoreOutcome(agent, version, result.warnings, result.publish_blockers)


def check_revision(agent: Agent, expected: int | None) -> None:
    if expected is not None and expected != agent.draft_revision:
        raise ProblemError(
            412,
            "draft_changed",
            "Draft changed",
            "This agent was saved somewhere else since you opened it. Reload to see the newer "
            "draft, or compare it with yours.",
            extra={"current_revision": agent.draft_revision},
        )


def apply_draft(agent: Agent, config: dict[str, Any], version: AgentVersion) -> None:
    agent.draft_config = draft_part(config)
    agent.draft_version_id = version.id
    agent.draft_revision = agent.draft_revision + 1
    agent.language = str(config.get("language") or agent.language)
    agent.updated_at = datetime.now(UTC)


async def snapshot_for_test(session: AsyncSession, agent_id: str) -> AgentVersion:
    """A version matching the current draft, for a test call on the draft (FR-029, R18).

    Reuses the draft version, or any version of the agent with the same content hash; otherwise
    records an unpublished ``source = test`` version. Pointers are never moved.
    """
    with tracer.start_as_current_span("agent_versions.snapshot_for_test"):
        agent = await lock_agent(session, agent_id)
        resolved = await resolve_snapshot(
            session,
            workspace_id=agent.workspace_id,
            agent_id=agent.id,
            agent_type=agent.type,
            config=agent.draft_config,
        )
        digest = content_hash(resolved)
        draft = await session.get(AgentVersion, agent.draft_version_id)
        if draft is not None and draft.content_hash.strip() == digest:
            return draft
        existing = await find_by_hash(session, agent.id, digest)
        if existing is not None:
            return existing
        result = await validate_config(
            agent.type, agent.draft_config, agent.id, session=session, workspace_id=agent.workspace_id
        )
        return await insert_version(
            session,
            workspace_id=agent.workspace_id,
            agent_id=agent.id,
            resolved_config=resolved,
            source="test",
            note=None,
            created_by=None,
            publish_blockers=result.publish_blockers,
            parent_version_id=agent.draft_version_id,
        )


async def create_version(
    session: AsyncSession,
    agent_id: str,
    config: Mapping[str, Any],
    *,
    note: str | None = None,
    source: str = "flow_publish",
    publish: bool = False,
    user_id: str | None = None,
    allow_http_webhook: bool = False,
) -> Recorded:
    """Record ``config`` as a version of ``agent_id`` (004 flow publish).

    Validates first (``422`` on errors), reuses any version of the agent with the same content
    hash, and with ``publish=True`` pins the result after checking its publish blockers. The
    draft is not changed; use ``agents.service.update_draft`` for that.
    """
    agent = await lock_agent(session, agent_id)
    result = await validate_config(
        agent.type,
        dict(config),
        agent.id,
        session=session,
        workspace_id=agent.workspace_id,
        allow_http_webhook=allow_http_webhook,
    )
    if result.errors:
        raise validation_failed(result.errors)
    if publish and result.publish_blockers:
        raise publish_blocked(result.publish_blockers)
    resolved = await resolve_snapshot(
        session,
        workspace_id=agent.workspace_id,
        agent_id=agent.id,
        agent_type=agent.type,
        config=result.normalized_config,
    )
    existing = await find_by_hash(session, agent.id, content_hash(resolved))
    created = existing is None
    version = existing or await insert_version(
        session,
        workspace_id=agent.workspace_id,
        agent_id=agent.id,
        resolved_config=resolved,
        source=source,
        note=note,
        created_by=user_id,
        publish_blockers=result.publish_blockers,
        parent_version_id=agent.draft_version_id,
    )
    if publish:
        agent.pinned_version_id = version.id
        await session.flush()
    return Recorded(version, created)
