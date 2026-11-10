"""Agents and their versions: the one save pipeline (T022, T032, T049, T074, T084, T089, T099;
research R2, R3, R13, R18).

Every function takes an ``AsyncSession`` scoped to the workspace by
``Database.transaction(workspace_id=...)`` (RLS). Every write to an agent row or a version goes
through here; saves follow data-model.md section 3:

* blocking errors -> 422 and nothing is written;
* unchanged content hash -> no version (``created = false``); a name change still updates the row;
* otherwise -> a new immutable version, ``draft_version_id`` moves, ``draft_revision`` + 1.

Version numbers are assigned while the agent row is locked (``SELECT ... FOR UPDATE``).

Interfaces for other features (plan.md "Interfaces exposed"):

* ``create_agent(session, actor, name=..., agent_type=..., ...)``: 004 flow create; records v1.
* ``update_draft(session, actor, agent_id, config=... | patch=..., expected_revision=None)``: 005
  attaching tools and knowledge bases, 007; validates and records a version when changed.
* ``create_version(session, agent_id, config, ...)``: record a version from a config (004 flow
  publish, 009 apply), deduplicated by content hash, optionally publishing it.
* ``snapshot_for_test(session, agent_id) -> AgentVersion``: a version matching the current draft
  (including resolved tools); reuses an identical version, else records ``source = test``. Never
  publishes (003 draft test calls, research R18).
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from callwright_contract.protocol import MAX_KNOWLEDGE_BASES
from opentelemetry import trace
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.agent_versions.canonical import content_hash
from app.agent_versions.models import AgentVersion
from app.agents import defaults, hooks
from app.agents.checks import validate_config
from app.agents.defaults import CURRENT_SCHEMA_VERSION
from app.agents.models import Agent
from app.agents.offered import template_overlay
from app.agents.schemas import MAX_TOOLS, NAME_MAX, upcast
from app.agents.validation import ConfigValidationResult
from app.agents.versions import draft_part, find_by_hash, get_for_agent, summary_of
from app.core.db import escape_like
from app.core.errors import ProblemError, not_found, validation_failed
from app.core.ids import is_valid_id, new_id
from app.core.pagination import page_window
from app.templates import service as templates
from app.voices.catalog import DEFAULT_LANGUAGE
from app.voices.catalog import load_catalog as load_voice_catalog

tracer = trace.get_tracer("app.agents")
COPY_SUFFIX = " (copy)"
SOURCES = ("create", "save", "restore", "template", "duplicate", "flow_publish", "test")


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


@dataclass(frozen=True)
class Recorded:
    version: AgentVersion
    created: bool


@dataclass(frozen=True)
class RestoreOutcome:
    agent: Agent
    version: AgentVersion
    warnings: list[dict[str, str]]
    publish_blockers: list[dict[str, str]]


def agent_in_use(attachments: list[hooks.Attachment]) -> ProblemError:
    return ProblemError(
        409,
        "agent_in_use",
        "Agent is in use",
        "Remove the agent from these channels before deleting it.",
        extra={"attachments": [{"kind": a.kind, "id": a.id, "label": a.label} for a in attachments]},
    )


def publish_blocked(issues: list[dict[str, str]]) -> ProblemError:
    return ProblemError(
        422,
        "publish_blocked",
        "Version cannot be published",
        "Fix the listed problems, save, and publish again.",
        errors=issues,
    )


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


def deep_merge(base: Mapping[str, Any], patch: Mapping[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(dict(base))
    for key, value in patch.items():
        if isinstance(value, Mapping) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def _language_of(*configs: Mapping[str, Any] | None) -> str | None:
    for config in configs:
        if config and isinstance(config.get("language"), str) and config["language"]:
            return str(config["language"])
    return None


async def get_agent(session: AsyncSession, agent_id: str, *, include_deleted: bool = False) -> Agent:
    agent = await session.get(Agent, agent_id)
    if agent is None or (agent.deleted_at is not None and not include_deleted):
        raise not_found("agent")
    return agent


async def lock_agent(session: AsyncSession, agent_id: str, *, include_deleted: bool = False) -> Agent:
    agent = (
        await session.execute(select(Agent).where(Agent.id == agent_id).with_for_update())
    ).scalar_one_or_none()
    if agent is None or (agent.deleted_at is not None and not include_deleted):
        raise not_found("agent")
    return agent


async def _validated(
    session: AsyncSession,
    agent_type: str,
    config: Mapping[str, Any],
    *,
    workspace_id: str,
    agent_id: str | None = None,
    allow_http_webhook: bool = False,
    previous_llm: tuple[str, str] | None = None,
    publish: bool = False,
) -> ConfigValidationResult:
    """``validate_config`` that refuses errors (422) and, when publishing, publish blockers."""
    result = await validate_config(
        agent_type,
        config,
        agent_id,
        session=session,
        workspace_id=workspace_id,
        allow_http_webhook=allow_http_webhook,
        previous_llm=previous_llm,
    )
    if result.errors:
        raise validation_failed(result.errors)
    if publish and result.publish_blockers:
        raise publish_blocked(result.publish_blockers)
    return result


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


async def _resolve_for(session: AsyncSession, agent: Agent, config: Mapping[str, Any]) -> dict[str, Any]:
    return await resolve_snapshot(
        session, workspace_id=agent.workspace_id, agent_id=agent.id, agent_type=agent.type, config=config
    )


async def _next_number(session: AsyncSession, agent_id: str) -> int:
    current = (
        await session.execute(
            select(func.max(AgentVersion.version_number)).where(AgentVersion.agent_id == agent_id)
        )
    ).scalar()
    return int(current or 0) + 1


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


def apply_draft(agent: Agent, config: dict[str, Any], version: AgentVersion) -> None:
    agent.draft_config = draft_part(config)
    agent.draft_version_id = version.id
    agent.draft_revision = agent.draft_revision + 1
    agent.language = str(config.get("language") or agent.language)
    agent.updated_at = datetime.now(UTC)


async def _draft_version_if_same(session: AsyncSession, agent: Agent, digest: str) -> AgentVersion | None:
    draft = await session.get(AgentVersion, agent.draft_version_id)
    return draft if draft is not None and draft.content_hash == digest else None


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
        draft_config=draft_part(normalized),
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
    version = await insert_version(
        session,
        workspace_id=actor.workspace_id,
        agent_id=agent_id,
        resolved_config=await _resolve_for(session, agent, normalized),
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
            if template.agent_type != agent_type:
                made = "a flow agent" if template.agent_type == "flow" else "a single-prompt agent"
                raise validation_failed(
                    [
                        {
                            "pointer": "/template_id",
                            "code": "invalid_format",
                            "message": f"This template creates {made}; create that type from it.",
                        }
                    ]
                )
            overlay, warnings = template_overlay(template.config)
            source, note = "template", f'Created from template "{template.name}" ({template.id})'
        if config:
            overlay = deep_merge(overlay, config)
        lang = language or _language_of(config, overlay)
        if lang is not None:
            overlay["language"] = lang
        result = await _validated(
            session,
            agent_type,
            overlay,
            workspace_id=actor.workspace_id,
            allow_http_webhook=actor.allow_http_webhook,
        )
        result.warnings[:0] = warnings
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
    agent = await lock_agent(session, agent_id)
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
        agent = await lock_agent(session, agent_id)
        check_revision(agent, expected_revision)
        if config is None:
            config = deep_merge(agent.draft_config, patch or {})
        previous = agent.draft_config.get("llm") or {}
        result = await _validated(
            session,
            agent.type,
            config,
            workspace_id=actor.workspace_id,
            agent_id=agent.id,
            allow_http_webhook=actor.allow_http_webhook,
            previous_llm=(str(previous.get("provider")), str(previous.get("model"))),
        )
        if name is not None and name != agent.name:
            agent.name = name
            agent.updated_at = datetime.now(UTC)
        resolved = await _resolve_for(session, agent, result.normalized_config)
        same = await _draft_version_if_same(session, agent, content_hash(resolved))
        if same is not None:
            await session.flush()
            span.set_attribute("agent.version_created", False)
            return Saved(agent, same, False, result)
        version = await insert_version(
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
        apply_draft(agent, result.normalized_config, version)
        await session.flush()
        span.set_attribute("agent.version_created", True)
        return Saved(agent, version, True, result)


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
    with tracer.start_as_current_span("agents.restore"):
        agent = await lock_agent(session, agent_id)
        check_revision(agent, expected_revision)
        source = await get_for_agent(session, agent.id, version_id)
        result = await _validated(
            session,
            agent.type,
            draft_part(upcast(source.config)),
            workspace_id=agent.workspace_id,
            agent_id=agent.id,
            allow_http_webhook=allow_http_webhook,
            publish=publish_now,
        )
        normalized = result.normalized_config
        version = await insert_version(
            session,
            workspace_id=agent.workspace_id,
            agent_id=agent.id,
            resolved_config=await _resolve_for(session, agent, normalized),
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
    """Record ``config`` as a version of ``agent_id`` (004 flow publish, 009 apply).

    Validates first (``422`` on errors), reuses any version of the agent with the same content
    hash, and with ``publish=True`` pins the result after checking its publish blockers. The
    draft is not changed; use ``update_draft`` (or ``apply_draft``) for that.
    """
    agent = await lock_agent(session, agent_id)
    result = await _validated(
        session,
        agent.type,
        dict(config),
        workspace_id=agent.workspace_id,
        agent_id=agent.id,
        allow_http_webhook=allow_http_webhook,
        publish=publish,
    )
    resolved = await _resolve_for(session, agent, result.normalized_config)
    existing = await find_by_hash(session, agent.id, content_hash(resolved))
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
    return Recorded(version, existing is None)


async def snapshot_for_test(session: AsyncSession, agent_id: str) -> AgentVersion:
    """A version matching the current draft, for a test call on the draft (FR-029, R18).

    Reuses the draft version, or any version of the agent with the same content hash; otherwise
    records an unpublished ``source = test`` version. Pointers are never moved.
    """
    with tracer.start_as_current_span("agents.snapshot_for_test"):
        agent = await lock_agent(session, agent_id)
        resolved = await _resolve_for(session, agent, agent.draft_config)
        digest = content_hash(resolved)
        existing = await _draft_version_if_same(session, agent, digest) or await find_by_hash(
            session, agent.id, digest
        )
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
    with tracer.start_as_current_span("agents.publish"):
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


ATTACHABLE = {"tool_ids": (MAX_TOOLS, "tools"), "kb_ids": (MAX_KNOWLEDGE_BASES, "knowledge bases")}


def check_attach_count(key: str, ids: list[str]) -> None:
    limit, noun = ATTACHABLE[key]
    if len(ids) > limit:
        raise validation_failed(
            [
                {
                    "pointer": f"/{key}",
                    "code": "too_many",
                    "message": f"An agent can use at most {limit} {noun}.",
                }
            ]
        )


async def attach(session: AsyncSession, actor: Actor, agent_id: str, key: str, ids: list[str]) -> Saved:
    """Replace an agent's attached tools (``tool_ids``) or knowledge bases (``kb_ids``)."""
    check_attach_count(key, ids)
    return await update_draft(session, actor, agent_id, patch={key: list(ids)})


async def detach(session: AsyncSession, actor: Actor, key: str, item_id: str, agent_ids: list[str]) -> None:
    """Remove a deleted tool or knowledge base from these agents' drafts."""
    for agent_id in agent_ids:
        agent = await get_agent(session, agent_id)
        remaining = [x for x in agent.draft_config.get(key) or [] if x != item_id]
        await update_draft(session, actor, agent_id, patch={key: remaining})


async def duplicate_agent(
    session: AsyncSession,
    actor: Actor,
    agent_id: str,
    name: str | None = None,
    version_id: str | None = None,
) -> Saved:
    """Copy an agent's draft, or one of its saved versions, into a new agent of the same type
    with its own version 1 (FR-020). History and live status are not copied."""
    source = await get_agent(session, agent_id)
    config = (
        (await get_for_agent(session, source.id, version_id)).config if version_id else source.draft_config
    )
    if name is None:
        name = source.name[: NAME_MAX - len(COPY_SUFFIX)].rstrip() + COPY_SUFFIX
    result = await _validated(
        session,
        source.type,
        config,
        workspace_id=actor.workspace_id,
        allow_http_webhook=actor.allow_http_webhook,
    )
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
    agent = await lock_agent(session, agent_id)
    attachments = await hooks.run_usage_checkers(
        hooks.UsageContext(session=session, workspace_id=actor.workspace_id, agent_id=agent.id)
    )
    if attachments:
        raise agent_in_use(attachments)
    now = datetime.now(UTC)
    agent.deleted_at = now
    agent.updated_at = now
    await session.flush()


@dataclass(frozen=True)
class ListedAgent:
    agent: Agent
    published_number: int | None
    published_created_at: datetime | None
    has_publish_blockers: bool


AgentStatus = Literal["live", "draft", "attention"]
AgentSort = Literal["updated", "name", "created"]


async def list_agents(
    session: AsyncSession,
    *,
    page: int,
    page_size: int,
    search: str | None = None,
    agent_type: str | None = None,
    status: AgentStatus | None = None,
    sort: AgentSort = "updated",
) -> tuple[list[ListedAgent], int, dict[str, int]]:
    """Agents, newest-updated first by default; ``search`` is a partial name or an exact agent id
    (R21). ``status``: live (published), draft (never published) or attention (the draft has
    publish blockers). Counts per status honour search and type, not status, so the tabs can show
    them all at once."""
    where: list[Any] = [Agent.deleted_at.is_(None)]
    if agent_type:
        where.append(Agent.type == agent_type)
    term = (search or "").strip()
    if term:
        if is_valid_id(term, "agt"):
            where.append(Agent.id == term)
        else:
            where.append(Agent.name.ilike(f"%{escape_like(term)}%"))
    pinned = aliased(AgentVersion)
    draft = aliased(AgentVersion)
    blocked = func.coalesce(func.jsonb_array_length(draft.publish_blockers), 0) > 0
    by_status = {
        "live": Agent.pinned_version_id.is_not(None),
        "draft": Agent.pinned_version_id.is_(None),
        "attention": blocked,
    }
    count_row = (
        await session.execute(
            select(
                func.count(),
                *(func.count().filter(cond) for cond in by_status.values()),
            )
            .select_from(Agent)
            .outerjoin(draft, draft.id == Agent.draft_version_id)
            .where(*where)
        )
    ).one()
    counts = {"all": int(count_row[0])} | {k: int(v) for k, v in zip(by_status, count_row[1:], strict=True)}
    if status:
        where.append(by_status[status])
    total = counts[status] if status else counts["all"]
    order = {
        "updated": (Agent.updated_at.desc(), Agent.id.desc()),
        "created": (Agent.created_at.desc(), Agent.id.desc()),
        "name": (func.lower(Agent.name).asc(), Agent.id.asc()),
    }[sort]
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
        .order_by(*order)
        .slice(*page_window(page, page_size))
    )
    out = [
        ListedAgent(agent, number, created, bool(blockers)) for agent, number, created, blockers in rows.all()
    ]
    return out, total, counts


def voice_label(config: Mapping[str, Any]) -> str:
    tts = config.get("tts") or {}
    voice = str(tts.get("voice_id") or "")
    provider = load_voice_catalog().tts_provider(str(tts.get("provider") or ""))
    if provider is not None:
        return provider.curated_name(voice) or voice
    return voice


def agent_defaults(agent_type: str, language: str | None) -> dict[str, Any]:
    lang = language if language and load_voice_catalog().language(language) else DEFAULT_LANGUAGE
    return defaults.default_config(agent_type, lang)
