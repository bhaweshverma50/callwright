"""Response bodies for the agents and agent_versions routes (contracts/agents.yaml,
contracts/agent_versions.yaml): ``AgentDetail``, ``AgentSummary``, ``SaveResult``,
``VersionSummary`` and ``VersionDetail``."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent_versions import service as versions
from app.agent_versions.models import AgentVersion
from app.agents.models import Agent
from app.agents.schemas import upcast
from app.agents.service import voice_label
from app.agents.validation import ConfigValidationResult
from app.workspaces.models import User


def etag(agent: Agent) -> str:
    return f'"{agent.draft_revision}"'


def parse_if_match(value: str | None) -> int | None:
    """``If-Match`` carries the draft revision ETag (``"3"``, ``W/"3"`` or ``3``)."""
    if value is None:
        return None
    text = value.strip()
    if text.startswith("W/"):
        text = text[2:]
    text = text.strip('"').strip()
    try:
        return int(text)
    except ValueError:
        return -1


def version_ref(version: AgentVersion) -> dict[str, Any]:
    return {
        "id": version.id,
        "version_number": version.version_number,
        "created_at": version.created_at.isoformat(),
    }


async def _version_refs(session: AsyncSession, agent: Agent) -> tuple[dict[str, Any], dict[str, Any] | None]:
    draft = await session.get(AgentVersion, agent.draft_version_id)
    assert draft is not None
    pinned = await session.get(AgentVersion, agent.pinned_version_id) if agent.pinned_version_id else None
    return version_ref(draft), version_ref(pinned) if pinned is not None else None


async def agent_detail(
    session: AsyncSession, agent: Agent, validation: ConfigValidationResult | None = None
) -> dict[str, Any]:
    draft_ref, pinned_ref = await _version_refs(session, agent)
    return {
        "id": agent.id,
        "name": agent.name,
        "type": agent.type,
        "template_id": agent.template_id,
        "draft_revision": agent.draft_revision,
        "draft_config": upcast(agent.draft_config),
        "draft_version": draft_ref,
        "published_version": pinned_ref,
        "publish_blockers": validation.publish_blockers if validation else [],
        "warnings": validation.warnings if validation else [],
        "created_at": agent.created_at.isoformat(),
        "updated_at": agent.updated_at.isoformat(),
    }


def agent_summary(
    agent: Agent, published: dict[str, Any] | None, has_publish_blockers: bool
) -> dict[str, Any]:
    config = agent.draft_config
    llm = config.get("llm") or {}
    return {
        "id": agent.id,
        "name": agent.name,
        "type": agent.type,
        "language": agent.language,
        "llm_model": f"{llm.get('provider', '')}/{llm.get('model', '')}",
        "voice_label": voice_label(config),
        "published_version": published,
        "has_publish_blockers": has_publish_blockers,
        "created_at": agent.created_at.isoformat(),
        "updated_at": agent.updated_at.isoformat(),
    }


async def agent_summary_for(session: AsyncSession, agent: Agent) -> dict[str, Any]:
    _, pinned_ref = await _version_refs(session, agent)
    draft = await session.get(AgentVersion, agent.draft_version_id)
    return agent_summary(agent, pinned_ref, bool(draft and draft.publish_blockers))


async def save_result(
    session: AsyncSession,
    agent: Agent,
    version: AgentVersion,
    *,
    created: bool,
    warnings: list[dict[str, str]],
    publish_blockers: list[dict[str, str]],
) -> dict[str, Any]:
    detail = await agent_detail(session, agent)
    detail["warnings"] = warnings
    detail["publish_blockers"] = publish_blockers
    return {
        "agent": detail,
        "created": created,
        "version": version_ref(version),
        "warnings": warnings,
        "publish_blockers": publish_blockers,
    }


async def _emails(session: AsyncSession, user_ids: set[str]) -> dict[str, str]:
    if not user_ids:
        return {}
    rows = await session.execute(select(User.id, User.email).where(User.id.in_(user_ids)))
    return {row.id: str(row.email) for row in rows}


async def version_summaries(
    session: AsyncSession, agent: Agent, rows: list[AgentVersion]
) -> list[dict[str, Any]]:
    linked = {r.restored_from_version_id for r in rows if r.restored_from_version_id} | {
        r.parent_version_id for r in rows if r.parent_version_id
    }
    numbers = await versions.numbers_for(session, {v for v in linked if v})
    emails = await _emails(session, {r.created_by for r in rows if r.created_by})
    return [version_summary(agent, r, numbers, emails) for r in rows]


def version_summary(
    agent: Agent, row: AgentVersion, numbers: dict[str, int], emails: dict[str, str]
) -> dict[str, Any]:
    return {
        "id": row.id,
        "version_number": row.version_number,
        "source": row.source,
        "note": row.note,
        "restored_from_version_number": numbers.get(row.restored_from_version_id or ""),
        "parent_version_number": numbers.get(row.parent_version_id or ""),
        "summary": row.summary,
        "created_by_email": emails.get(row.created_by or ""),
        "created_at": row.created_at.isoformat(),
        "content_hash": row.content_hash.strip(),
        "is_published": agent.pinned_version_id == row.id,
        "is_draft": agent.draft_version_id == row.id,
        "has_publish_blockers": bool(row.publish_blockers),
    }


async def version_detail(session: AsyncSession, agent: Agent, row: AgentVersion) -> dict[str, Any]:
    (summary,) = await version_summaries(session, agent, [row])
    return {
        **summary,
        "agent_id": row.agent_id,
        "schema_version": row.schema_version,
        "config": upcast(row.config),
        "publish_blockers": row.publish_blockers,
    }
