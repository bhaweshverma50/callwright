"""Pieces shared by phone numbers, outbound calls and WhatsApp channels (010): dependencies,
agent checks, the webhook address rule, the SIP host, active-call counts and the delete flow
(dispatch rule first, then the trunks, or ``draining`` until the last call ends)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from callwright_contract.calls import ACTIVE_STATUSES
from callwright_contract.url_guard import CheckedUrl, UrlNotAllowed, check_url
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.calls.models import Call
from app.calls.ports import registry
from app.channels.sip import SipError, SipGateway
from app.core import url_guard
from app.core.config import Settings
from app.core.db import Database
from app.core.errors import ProblemError, field_error, validation_failed
from app.core.secrets import KeyWrapper, key_wrapper

NOT_CONFIGURED_HOST = "sip.not-configured.invalid"


@dataclass
class ChannelDeps:
    db: Database
    settings: Settings
    sip: SipGateway

    @property
    def wrapper(self) -> KeyWrapper:
        return key_wrapper(self.settings)


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


async def checked_webhook_url(settings: Settings, url: str) -> CheckedUrl:
    """An inbound webhook address under the customer webhook safety rules (FR-033); raises
    ``UrlNotAllowed``."""
    return await check_url(
        url,
        allow_http=settings.webhooks_allow_http,
        allow_private=settings.webhooks_allow_private,
        resolver=url_guard.resolver,
    )


async def check_webhook_url(
    settings: Settings, url: str | None, pointer: str = "/inbound_webhook_url"
) -> None:
    if not url:
        return
    try:
        await checked_webhook_url(settings, url)
    except UrlNotAllowed as exc:
        raise validation_failed([field_error(pointer, exc.reason, exc.detail)]) from None


def sip_host(settings: Settings) -> str:
    """Where carriers and WhatsApp send SIP; a placeholder that can never resolve until set."""
    return settings.livekit_sip_host or NOT_CONFIGURED_HOST


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


def status_view(status: str) -> str:
    """A deleted row still shows as ``draining`` to the client that deleted it."""
    return "draining" if status == "deleted" else status


class _SipBacked(Protocol):
    status: str
    status_detail: str | None
    updated_at: datetime
    lk_dispatch_rule_id: str | None

    @property
    def trunk_ids(self) -> tuple[str | None, ...]: ...


async def remove_sip_objects(sip: SipGateway, row: _SipBacked) -> None:
    """Delete the row's dispatch rule and trunks (raises ``SipError`` on the first failure)."""
    if row.lk_dispatch_rule_id:
        await sip.delete_dispatch_rule(row.lk_dispatch_rule_id)
    for trunk_id in row.trunk_ids:
        if trunk_id:
            await sip.delete_trunk(trunk_id)


async def finish_or_drain(
    sip: SipGateway,
    session: AsyncSession,
    row: _SipBacked,
    finish: Callable[[AsyncSession, Any], Awaitable[None]],
) -> bool:
    """Remove the SIP objects and ``finish`` the delete. A SIP failure leaves the row
    ``draining`` for the drain cron (new calls are already refused). Returns whether it was
    deleted."""
    try:
        await remove_sip_objects(sip, row)
    except SipError as exc:
        row.status = "draining"
        row.status_detail = f"Cleanup pending: {exc}"[:500]
        await session.flush()
        return False
    await finish(session, row)
    return True


async def delete_or_drain(
    sip: SipGateway,
    session: AsyncSession,
    row: _SipBacked,
    *,
    active: int,
    finish: Callable[[AsyncSession, Any], Awaitable[None]],
    after_rule: Callable[[], Awaitable[None]] | None = None,
) -> bool:
    """Delete a number or WhatsApp channel (010 R8): the dispatch rule goes at once so no new
    call arrives (502 ``routing_update_failed`` when SIP refuses), then the row is deleted, or
    left ``draining`` while ``active`` calls finish. Returns whether it was deleted."""
    if row.lk_dispatch_rule_id:
        try:
            await sip.delete_dispatch_rule(row.lk_dispatch_rule_id)
            row.lk_dispatch_rule_id = None
        except SipError as exc:
            raise ProblemError(502, "routing_update_failed", "Routing update failed", str(exc)) from None
    if after_rule is not None:
        await after_rule()
    row.updated_at = datetime.now(UTC)
    if active:
        row.status = "draining"
        await session.flush()
        return False
    return await finish_or_drain(sip, session, row, finish)
