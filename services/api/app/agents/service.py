"""Agents: create, read, rename, save draft, list, duplicate, delete (T032, T049, T074, T084).

Every function takes an ``AsyncSession`` scoped to the workspace by
``Database.transaction(workspace_id=...)`` (RLS). Saves follow data-model.md section 3:

* blocking errors -> 422 and nothing is written;
* unchanged content hash -> no version (``created = false``); a name change still updates the row;
* otherwise -> a new immutable version, ``draft_version_id`` moves, ``draft_revision`` + 1.

Interfaces for other features (plan.md "Interfaces exposed"):

* ``create_agent(session, actor, name=..., agent_type=..., ...)``: 004 flow create; records v1.
* ``update_draft(session, actor, agent_id, config=... | patch=..., expected_revision=None)``: 005
  attaching tools and knowledge bases, 007; validates and records a version when changed.
* ``validate_config(agent_type, config, agent_id=None, session=..., workspace_id=...)``: 004
  global settings, 008 variants; the same code as save.
* ``validate_override(path, value)``: 004 flow-node overrides, against the shared ``controls``
  range table (FR-047).
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from opentelemetry import trace
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.agent_versions import service as versions
from app.agent_versions.canonical import content_hash
from app.agent_versions.models import AgentVersion
from app.agents import defaults, hooks
from app.agents.checks import validate_config
from app.agents.models import Agent
from app.agents.validation import ConfigValidationResult, clamp_override, validate_override
from app.core.errors import ProblemError, not_found, validation_failed
from app.core.ids import is_valid_id, new_id
from app.templates import service as templates
from app.voices.catalog import load_catalog as load_voice_catalog

__all__ = [
    "Actor",
    "clamp_override",
    "create_agent",
    "delete_agent",
    "duplicate_agent",
    "get_agent",
    "list_agents",
    "rename_agent",
    "update_draft",
    "validate_config",
    "validate_override",
]

tracer = trace.get_tracer("app.agents")
COPY_SUFFIX = " (copy)"


@dataclass(frozen=True)
class Actor:
    workspace_id: str
    user_id: str | None
    allow_http_webhook: bool = False


@dataclass(frozen=True)
class Saved:
    agent: Agent
    version: AgentVersion
    created: bool
    validation: ConfigValidationResult


def agent_in_use(attachments: list[hooks.Attachment]) -> ProblemError:
    return ProblemError(
        409,
        "agent_in_use",
        "Agent is in use",
        "Remove the agent from these channels before deleting it.",
        extra={"attachments": [{"kind": a.kind, "id": a.id, "label": a.label} for a in attachments]},
    )


def _deep_merge(base: dict[str, Any], patch: Mapping[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(base)
    for key, value in patch.items():
        if isinstance(value, Mapping) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def _language_of(*configs: Mapping[str, Any] | None) -> str | None:
    for config in configs:
        if config and isinstance(config.get("language"), str) and config["language"]:
            return str(config["language"])
    return None


async def get_agent(session: AsyncSession, agent_id: str) -> Agent:
    agent = await session.get(Agent, agent_id)
    if agent is None or agent.deleted_at is not None:
        raise not_found("agent")
    return agent


async def _write_new_agent(
    session: AsyncSession,
    actor: Actor,
    *,
    name: str,
    agent_type: str,
    result: ConfigValidationResult,
    source: str,
    note: str | None,
    template_id: str | None,
) -> Saved:
    agent_id = new_id("agt")
    version_id = new_id("agv")
    normalized = result.normalized_config
    now = datetime.now(UTC)
    agent = Agent(
        id=agent_id,
        workspace_id=actor.workspace_id,
        name=name,
        type=agent_type,
        language=str(normalized["language"]),
        draft_config=versions.draft_part(normalized),
        draft_revision=1,
        draft_version_id=version_id,
        pinned_version_id=None,
        template_id=template_id,
        created_by=actor.user_id,
        created_at=now,
        updated_at=now,
    )
    session.add(agent)
    await session.flush()
    resolved = await versions.resolve_snapshot(
        session, workspace_id=actor.workspace_id, agent_id=agent_id, agent_type=agent_type, config=normalized
    )
    version = await versions.insert_version(
        session,
        workspace_id=actor.workspace_id,
        agent_id=agent_id,
        resolved_config=resolved,
        source=source,
        note=note,
        created_by=actor.user_id,
        publish_blockers=result.publish_blockers,
        parent_version_id=None,
        version_id=version_id,
    )
    return Saved(agent, version, True, result)


async def create_agent(
    session: AsyncSession,
    actor: Actor,
    *,
    name: str,
    agent_type: str,
    language: str | None = None,
    config: Mapping[str, Any] | None = None,
    template_id: str | None = None,
) -> Saved:
    """Create an agent from defaults, a template and/or a partial config; records version 1."""
    with tracer.start_as_current_span("agents.create"):
        overlay: dict[str, Any] = {}
        warnings: list[dict[str, str]] = []
        source, note = "create", None
        if template_id is not None:
            template = await templates.get_template(session, template_id)
            if template is None:
                raise not_found("template")
            if agent_type != "single_prompt":
                raise validation_failed(
                    [
                        {
                            "pointer": "/template_id",
                            "code": "invalid_format",
                            "message": "Templates create single-prompt agents.",
                        }
                    ]
                )
            overlay, warnings = templates.partial_config(template.config)
            source, note = "template", f'Created from template "{template.name}" ({template.id})'
        if config:
            overlay = _deep_merge(overlay, config)
        lang = language or _language_of(config, overlay)
        if lang is not None:
            overlay["language"] = lang
        result = await validate_config(
            agent_type,
            overlay,
            session=session,
            workspace_id=actor.workspace_id,
            allow_http_webhook=actor.allow_http_webhook,
        )
        result.warnings[:0] = warnings
        if result.errors:
            raise validation_failed(result.errors)
        return await _write_new_agent(
            session,
            actor,
            name=name,
            agent_type=agent_type,
            result=result,
            source=source,
            note=note,
            template_id=template_id,
        )


async def rename_agent(session: AsyncSession, agent_id: str, name: str) -> Agent:
    agent = await versions.lock_agent(session, agent_id)
    if agent.name != name:
        agent.name = name
        agent.updated_at = datetime.now(UTC)
        await session.flush()
    return agent


async def update_draft(
    session: AsyncSession,
    actor: Actor,
    agent_id: str,
    *,
    config: Mapping[str, Any] | None = None,
    patch: Mapping[str, Any] | None = None,
    expected_revision: int | None = None,
    name: str | None = None,
    note: str | None = None,
) -> Saved:
    """Save the draft (``config`` replaces it, ``patch`` is deep-merged into it)."""
    with tracer.start_as_current_span("agents.save_draft") as span:
        agent = await versions.lock_agent(session, agent_id)
        versions.check_revision(agent, expected_revision)
        if config is None:
            config = _deep_merge(agent.draft_config, patch or {})
        previous = agent.draft_config.get("llm") or {}
        result = await validate_config(
            agent.type,
            config,
            agent.id,
            session=session,
            workspace_id=actor.workspace_id,
            allow_http_webhook=actor.allow_http_webhook,
            previous_llm=(str(previous.get("provider")), str(previous.get("model"))),
        )
        if result.errors:
            raise validation_failed(result.errors)
        if name is not None and name != agent.name:
            agent.name = name
            agent.updated_at = datetime.now(UTC)
        resolved = await versions.resolve_snapshot(
            session,
            workspace_id=agent.workspace_id,
            agent_id=agent.id,
            agent_type=agent.type,
            config=result.normalized_config,
        )
        draft_version = await session.get(AgentVersion, agent.draft_version_id)
        assert draft_version is not None
        if draft_version.content_hash.strip() == content_hash(resolved):
            await session.flush()
            span.set_attribute("agent.version_created", False)
            return Saved(agent, draft_version, False, result)
        version = await versions.insert_version(
            session,
            workspace_id=agent.workspace_id,
            agent_id=agent.id,
            resolved_config=resolved,
            source="save",
            note=note,
            created_by=actor.user_id,
            publish_blockers=result.publish_blockers,
            parent_version_id=agent.draft_version_id,
        )
        versions.apply_draft(agent, result.normalized_config, version)
        await session.flush()
        span.set_attribute("agent.version_created", True)
        return Saved(agent, version, True, result)


async def duplicate_agent(
    session: AsyncSession, actor: Actor, agent_id: str, name: str | None = None
) -> Saved:
    """Copy an agent's draft into a new agent of the same type with its own version 1 (FR-020)."""
    source = await get_agent(session, agent_id)
    if name is None:
        name = source.name[: 80 - len(COPY_SUFFIX)].rstrip() + COPY_SUFFIX
    result = await validate_config(
        source.type,
        source.draft_config,
        session=session,
        workspace_id=actor.workspace_id,
        allow_http_webhook=actor.allow_http_webhook,
    )
    if result.errors:
        raise validation_failed(result.errors)
    saved = await _write_new_agent(
        session,
        actor,
        name=name,
        agent_type=source.type,
        result=result,
        source="duplicate",
        note=f"Duplicated from {source.name} ({source.id})",
        template_id=None,
    )
    await hooks.run_duplicate_hooks(
        hooks.DuplicateContext(
            session=session,
            workspace_id=actor.workspace_id,
            source_agent_id=source.id,
            new_agent_id=saved.agent.id,
            config=saved.agent.draft_config,
        )
    )
    return saved


async def delete_agent(session: AsyncSession, actor: Actor, agent_id: str) -> None:
    """Soft delete; refused while a live channel uses the agent (FR-021, R14)."""
    agent = await versions.lock_agent(session, agent_id)
    attachments = await hooks.run_usage_checkers(
        hooks.UsageContext(session=session, workspace_id=actor.workspace_id, agent_id=agent.id)
    )
    if attachments:
        raise agent_in_use(attachments)
    now = datetime.now(UTC)
    agent.deleted_at = now
    agent.updated_at = now
    await session.flush()


# List ------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class ListedAgent:
    agent: Agent
    published_number: int | None
    published_created_at: datetime | None
    has_publish_blockers: bool


def _escape_like(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


async def list_agents(
    session: AsyncSession,
    *,
    page: int,
    page_size: int,
    search: str | None = None,
    agent_type: str | None = None,
) -> tuple[list[ListedAgent], int]:
    """Agents newest-updated first; ``search`` is a partial name or an exact agent id (R21)."""
    where: list[Any] = [Agent.deleted_at.is_(None)]
    if agent_type:
        where.append(Agent.type == agent_type)
    term = (search or "").strip()
    if term:
        if is_valid_id(term, "agt"):
            where.append(Agent.id == term)
        else:
            where.append(Agent.name.ilike(f"%{_escape_like(term)}%"))
    total = int((await session.execute(select(func.count()).select_from(Agent).where(*where))).scalar_one())
    pinned = aliased(AgentVersion)
    draft = aliased(AgentVersion)
    rows = await session.execute(
        select(
            Agent,
            pinned.version_number,
            pinned.created_at,
            func.jsonb_array_length(draft.publish_blockers),
        )
        .outerjoin(pinned, and_(pinned.id == Agent.pinned_version_id))
        .outerjoin(draft, and_(draft.id == Agent.draft_version_id))
        .where(*where)
        .order_by(Agent.updated_at.desc(), Agent.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    out = [
        ListedAgent(agent, number, created, bool(blockers)) for agent, number, created, blockers in rows.all()
    ]
    return out, total


def voice_label(config: Mapping[str, Any]) -> str:
    tts = config.get("tts") or {}
    voice = str(tts.get("voice_id") or "")
    provider = load_voice_catalog().tts_provider(str(tts.get("provider") or ""))
    if provider is not None:
        return provider.curated_name(voice) or voice
    return voice


def agent_defaults(agent_type: str, language: str | None) -> dict[str, Any]:
    lang = language if language and load_voice_catalog().language(language) else defaults.DEFAULT_LANGUAGE
    return defaults.default_config(agent_type, lang)
