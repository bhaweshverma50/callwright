"""``validate_config``: the pure validator plus its database-backed inputs (T019, research R10).

Used by draft saves, creates, restores, publishing, ``POST /v1/agents/validate`` and other
features (004 global settings, 008 variants), so the editor and the server never disagree.
Lives apart from ``agents.service`` so ``agent_versions.service`` can use it without an import
cycle; ``agents.service.validate_config`` re-exports it.
"""

from __future__ import annotations

from typing import Any

from opentelemetry import trace
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents import hooks
from app.agents.validation import ConfigValidationResult, PureContext, validate_pure
from app.agents.webhook_url import Resolver, check_resolved
from app.core import url_guard
from app.pricing import engine
from app.pricing import service as pricing
from app.voices.models import AmbientAudioFile

tracer = trace.get_tracer("app.agents")


def _host_resolver() -> Resolver | None:
    """``core.url_guard.resolver`` (the test seam) in the host-only form ``check_resolved`` takes."""
    seam = url_guard.resolver
    if seam is None:
        return None

    async def resolve(host: str) -> list[str]:
        return await seam(host, 443)

    return resolve


async def pricing_now(session: AsyncSession) -> engine.Catalog | None:
    try:
        return await pricing.catalog_at(session)
    except pricing.CatalogUnavailable:
        return None


def _upload_key(config: Any) -> str | None:
    if not isinstance(config, dict):
        return None
    source = ((config.get("advanced") or {}).get("background_audio") or {}).get("source")
    if isinstance(source, dict) and source.get("kind") == "upload" and isinstance(source.get("key"), str):
        return str(source["key"])
    return None


async def _ambient_keys(session: AsyncSession, key: str | None) -> frozenset[str] | None:
    if key is None:
        return None
    rows = await session.execute(
        select(AmbientAudioFile.storage_key).where(
            AmbientAudioFile.storage_key == key, AmbientAudioFile.deleted_at.is_(None)
        )
    )
    return frozenset(str(k) for k in rows.scalars())


async def validate_config(
    agent_type: str,
    config: Any,
    agent_id: str | None = None,
    *,
    session: AsyncSession | None = None,
    workspace_id: str | None = None,
    allow_http_webhook: bool = False,
    previous_llm: tuple[str, str] | None = None,
    run_hooks: bool = True,
) -> ConfigValidationResult:
    """Validate ``config`` for an agent of ``agent_type``; same rules as save and publish.

    With a ``session`` (scoped to ``workspace_id``) prices come from the pricing catalog in
    effect now, uploaded background sounds are checked, the webhook host is resolved and the
    hooks registered by other features run. Without one, only the pure checks run.
    """
    with tracer.start_as_current_span("agents.validate_config") as span:
        span.set_attribute("agent.type", agent_type)
        ctx = PureContext(
            pricing=await pricing_now(session) if session is not None else None,
            allow_http_webhook=allow_http_webhook,
            previous_llm=previous_llm,
            workspace_id=workspace_id,
            ambient_keys=await _ambient_keys(session, _upload_key(config)) if session is not None else None,
        )
        result = validate_pure(agent_type, config, ctx)
        url = (result.normalized_config.get("advanced") or {}).get("webhook_url")
        if (
            session is not None
            and isinstance(url, str)
            and url
            and not any(e["pointer"] == "/advanced/webhook_url" for e in result.errors)
        ):
            issue = await check_resolved(url, _host_resolver())
            if issue is not None:
                result.errors.append(
                    {"pointer": "/advanced/webhook_url", "code": issue.code, "message": issue.message}
                )
        if run_hooks:
            normalized = result.normalized_config

            def make_context(block: str) -> hooks.HookContext:
                return hooks.HookContext(
                    block=block,
                    value=normalized.get(block),
                    config=normalized,
                    agent_type=agent_type,
                    workspace_id=workspace_id,
                    agent_id=agent_id,
                    session=session,
                )

            extra = await hooks.run_validators(make_context)
            result.errors.extend(extra.errors)
            result.publish_blockers.extend(extra.publish_blockers)
            result.warnings.extend(extra.warnings)
        result.valid = not result.errors
        span.set_attribute("validation.errors", len(result.errors))
        return result
