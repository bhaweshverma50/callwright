"""Response bodies for the agents and agent_versions routes (contracts/agents.yaml,
contracts/agent_versions.yaml): ``AgentDetail``, ``AgentSummary``, ``SaveResult``,
``VersionSummary`` and ``VersionDetail``."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent_versions.models import AgentVersion
from app.agents import vendors, versions
from app.agents.models import Agent
from app.agents.schemas import upcast
from app.agents.service import Actor, voice_label
from app.agents.validation import ConfigValidationResult
from app.core.auth import Principal
from app.voices.catalog import load_catalog as load_voice_catalog
from app.workspaces.models import User


def actor(request: Request, principal: Principal) -> Actor:
    """The agents ``Actor`` for a request; http webhooks only where Settings allow them."""
    return Actor(
        workspace_id=principal.workspace_id,
        user_id=principal.user_id,
        allow_http_webhook=request.app.state.settings.allow_http_webhooks,
    )


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


def stt_label(stt: Mapping[str, Any]) -> str:
    """``Deepgram Nova 3``; ``Deepgram (Auto)`` when no model is picked."""
    provider_id = str(stt.get("provider") or "")
    provider = load_voice_catalog().stt_provider(provider_id)
    if provider is None:
        return provider_id
    model_id = stt.get("model")
    model = next((m for m in provider.models if m.id == model_id), None) if model_id else None
    if model_id:
        return f"{provider.label} {model.label if model is not None else model_id}"
    return f"{provider.label} (Auto)"


def _node_overrides(graph: Mapping[str, Any] | None) -> list[Mapping[str, Any]]:
    nodes = graph.get("nodes") if isinstance(graph, Mapping) else None
    out: list[Mapping[str, Any]] = []
    for node in nodes if isinstance(nodes, list) else []:
        cfg = node.get("config") if isinstance(node, Mapping) else None
        ov = cfg.get("overrides") if isinstance(cfg, Mapping) else None
        if isinstance(ov, Mapping) and ov:
            out.append(ov)
    return out


def flow_extras(config: Mapping[str, Any], graph: Mapping[str, Any] | None) -> dict[str, list[str]]:
    """The models, voices and speech recognition a flow's nodes use besides the agent's own."""
    base_llm = dict(config.get("llm") or {})
    base_tts = dict(config.get("tts") or {})
    base_stt = dict(config.get("stt") or {})
    llm_main = f"{base_llm.get('provider', '')}/{base_llm.get('model', '')}"
    main = {"llm": llm_main, "voice": voice_label(config), "stt": stt_label(base_stt)}
    found: dict[str, list[str]] = {"llm": [], "voice": [], "stt": []}

    def add(kind: str, value: str) -> None:
        if value and value != main[kind] and value not in found[kind]:
            found[kind].append(value)

    for ov in _node_overrides(graph):
        llm = ov.get("llm")
        if isinstance(llm, Mapping) and (llm.get("provider") or llm.get("model")):
            add(
                "llm",
                f"{llm.get('provider') or base_llm.get('provider', '')}/"
                f"{llm.get('model') or base_llm.get('model', '')}",
            )
        tts = ov.get("tts")
        if isinstance(tts, Mapping) and tts:
            merged = {**base_tts, **{k: v for k, v in tts.items() if v is not None}}
            if tts.get("provider") and tts["provider"] != base_tts.get("provider"):
                merged = {k: v for k, v in merged.items() if k not in ("model", "voice_id")}
                merged.update({k: v for k, v in tts.items() if k in ("model", "voice_id") and v})
            add("voice", voice_label({"tts": merged}))
        stt = ov.get("stt")
        if isinstance(stt, Mapping) and stt:
            merged = {**base_stt, **{k: v for k, v in stt.items() if v is not None}}
            if stt.get("provider") and stt["provider"] != base_stt.get("provider"):
                merged = {"provider": stt["provider"], "model": stt.get("model")}
            add("stt", stt_label(merged))
    return found


def agent_summary(
    agent: Agent,
    published: dict[str, Any] | None,
    has_publish_blockers: bool,
    *,
    config: Mapping[str, Any] | None = None,
    vendor_warnings: list[str] | None = None,
    flow_graph: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """List row. ``config`` is what the card shows: the published version's vendors when the
    agent has one (it is what calls run), else the draft's."""
    config = config if config is not None else agent.draft_config
    llm = config.get("llm") or {}
    extras = flow_extras(config, flow_graph) if agent.type == "flow" else {"llm": [], "voice": [], "stt": []}
    return {
        "id": agent.id,
        "name": agent.name,
        "type": agent.type,
        "language": agent.language,
        "llm_model": f"{llm.get('provider', '')}/{llm.get('model', '')}",
        "llm_extra_models": extras["llm"],
        "voice_label": voice_label(config),
        "voice_extra_labels": extras["voice"],
        "stt_label": stt_label(config.get("stt") or {}),
        "stt_extra_labels": extras["stt"],
        "published_version": published,
        "has_publish_blockers": has_publish_blockers,
        "vendor_warnings": vendor_warnings or [],
        "created_at": agent.created_at.isoformat(),
        "updated_at": agent.updated_at.isoformat(),
    }


async def agent_summary_for(session: AsyncSession, agent: Agent) -> dict[str, Any]:
    _, pinned_ref = await _version_refs(session, agent)
    draft = await session.get(AgentVersion, agent.draft_version_id)
    pinned = await session.get(AgentVersion, agent.pinned_version_id) if agent.pinned_version_id else None
    config = pinned.config if pinned is not None else agent.draft_config
    return agent_summary(
        agent,
        pinned_ref,
        bool(draft and draft.publish_blockers),
        config=config,
        vendor_warnings=vendors.messages(agent.draft_config, pinned.config if pinned else None),
    )


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
        "content_hash": row.content_hash,
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
