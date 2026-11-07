"""Pieces shared by phone numbers, outbound calls and WhatsApp channels (010)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from callwright_contract.calls import ACTIVE_STATUSES
from callwright_contract.url_guard import UrlNotAllowed, check_url
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.calls.models import Call
from app.calls.ports import registry
from app.core.config import Settings
from app.core.db import Database
from app.core.errors import ProblemError, field_error, validation_failed
from app.core.secrets import KeyWrapper, key_wrapper
from app.phone_numbers.sip import SipGateway


@dataclass
class ChannelDeps:
    db: Database
    settings: Settings
    sip: SipGateway

    @property
    def wrapper(self) -> KeyWrapper:
        return key_wrapper(self.settings)


def _resolver(one_arg: Any) -> Any:
    """Adapt 002's test resolver (``host`` only) to ``url_guard``'s ``(host, port)`` form."""
    if one_arg is None:
        return None

    async def resolve(host: str, port: int) -> list[str]:
        result: list[str] = await one_arg(host)
        return result

    return resolve


def iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


async def agent_state(session: AsyncSession, agent_id: str) -> str:
    """``published``, ``unpublished`` or ``missing`` (deleted or another workspace: RLS), through
    003's agent versions port so channels and admission agree."""
    port = registry.agent_versions
    if not await port.agent_exists(session, agent_id):
        return "missing"
    return "published" if await port.get_published(session, agent_id) is not None else "unpublished"


async def require_published(session: AsyncSession, fields: dict[str, str | None]) -> None:
    """422 with one error per agent field that is unknown or has no published version."""
    errors = []
    for name, agent_id in fields.items():
        if agent_id is None:
            continue
        state = await agent_state(session, agent_id)
        if state == "missing":
            errors.append(
                field_error(f"/{name}", "not_found", "No agent with that id exists in this workspace.")
            )
        elif state == "unpublished":
            errors.append(
                field_error(f"/{name}", "agent_not_published", "Publish this agent before attaching it.")
            )
    if errors:
        raise validation_failed(errors)


async def check_webhook_url(
    settings: Settings, url: str | None, pointer: str = "/inbound_webhook_url"
) -> None:
    """Inbound webhook addresses follow the customer webhook safety rules (FR-033)."""
    if not url:
        return
    from app.agents import checks

    try:
        await check_url(
            url,
            allow_http=settings.webhooks_allow_http,
            allow_private=settings.webhooks_allow_private,
            resolver=_resolver(checks.webhook_resolver),
        )
    except UrlNotAllowed as exc:
        raise validation_failed([field_error(pointer, exc.reason, exc.detail)]) from None


async def active_counts(session: AsyncSession, column: Any, ids: Sequence[str]) -> dict[str, int]:
    if not ids:
        return {}
    rows = await session.execute(
        select(column, func.count())
        .where(column.in_(list(ids)), Call.status.in_(tuple(ACTIVE_STATUSES)))
        .group_by(column)
    )
    return {str(k): int(n) for k, n in rows.all()}


def conflict(code: str, detail: str, **extra: Any) -> ProblemError:
    return ProblemError(409, code, "Conflict", detail, extra=extra or None)
