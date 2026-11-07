"""Phone numbers: import, list, edit, agents, retry and safe deletion (010 T017, T039, T040, T043).

Import saves the row as ``provisioning`` first (the global unique index on ``e164`` is the race
guard), then creates the LiveKit SIP objects synchronously and stores ``active`` or ``error``.
Edits that touch routing call the SIP service before the database, so a failed SIP update
changes nothing (502 ``routing_update_failed``). Deleting a number with active calls is refused
unless ``when_idle``: the dispatch rule goes at once, the number turns ``draining`` and the drain
cron (``jobs.py``) removes the trunks once the last call ends. Rows are soft-deleted so past
calls keep their number and label.

Agents in use by a number cannot be deleted (002 ``register_usage_checker``): the builder
answers 409 ``agent_in_use`` listing the numbers, so no attachment ever points at a deleted agent.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents import hooks as agent_hooks
from app.calls.models import Call
from app.core.auth import Principal
from app.core.errors import ProblemError, not_found
from app.core.ids import new_id
from app.core.pagination import page_meta
from app.core.secrets import delete_secret, get_secret, put_secret
from app.phone_numbers import provisioning, validation
from app.phone_numbers.models import PhoneNumber
from app.phone_numbers.schemas import PhoneNumberImport, PhoneNumberUpdate
from app.phone_numbers.shared import (
    ChannelDeps,
    active_counts,
    check_webhook_url,
    conflict,
    iso,
    require_published,
)
from app.phone_numbers.sip import SipError

logger = logging.getLogger(__name__)

PASSWORD_SECRET = "phone_numbers/{id}/auth_password"  # noqa: S105 - a secret name, not a value
NOT_CONFIGURED_HOST = "sip.not-configured.invalid"


def sip_host(deps: ChannelDeps) -> str:
    return deps.settings.livekit_sip_host or NOT_CONFIGURED_HOST


def sip_settings(deps: ChannelDeps) -> dict[str, Any]:
    host = sip_host(deps)
    return {
        "origination_uri": f"sip:{host}",
        "direct_uri_template": f"sip:{{e164}}@{host}",
        "transports": ["udp", "tcp", "tls"],
        "telephony_enabled": deps.sip.live,
    }


def to_out(deps: ChannelDeps, number: PhoneNumber, active: int) -> dict[str, Any]:
    status = "draining" if number.status == "deleted" else number.status
    return {
        "id": number.id,
        "e164": number.e164,
        "label": number.label,
        "termination_address": number.termination_address,
        "transport": number.transport,
        "auth_username": number.auth_username,
        "has_auth_password": number.auth_password_secret is not None,
        "inbound_allowed_cidrs": [str(c) for c in number.inbound_allowed_cidrs or []],
        "inbound_agent_id": number.inbound_agent_id,
        "outbound_agent_id": number.outbound_agent_id,
        "inbound_webhook_url": number.inbound_webhook_url,
        "direct_uri": f"sip:{number.e164}@{sip_host(deps)}",
        "status": status,
        "status_detail": number.status_detail,
        "active_call_count": active,
        "created_at": iso(number.created_at),
        "updated_at": iso(number.updated_at),
    }


async def _out(deps: ChannelDeps, session: AsyncSession, number: PhoneNumber) -> dict[str, Any]:
    counts = await active_counts(session, Call.phone_number_id, [number.id])
    return to_out(deps, number, counts.get(number.id, 0))


async def _load(session: AsyncSession, number_id: str, *, lock: bool = False) -> PhoneNumber:
    query = select(PhoneNumber).where(PhoneNumber.id == number_id, PhoneNumber.deleted_at.is_(None))
    if lock:
        query = query.with_for_update()
    number = (await session.execute(query)).scalar_one_or_none()
    if number is None:
        raise not_found("phone number")
    return number


async def _password(deps: ChannelDeps, session: AsyncSession, number: PhoneNumber) -> str | None:
    if number.auth_password_secret is None:
        return None
    return await get_secret(session, deps.wrapper, number.workspace_id, number.auth_password_secret)


def _apply_result(number: PhoneNumber, result: provisioning.ProvisionResult, now: datetime) -> None:
    number.lk_inbound_trunk_id = result.objects.inbound_trunk_id
    number.lk_outbound_trunk_id = result.objects.outbound_trunk_id
    number.lk_dispatch_rule_id = result.objects.dispatch_rule_id
    number.status = "error" if result.error else "active"
    number.status_detail = result.error[:500] if result.error else None
    number.updated_at = now


def _invalid(pointer: str, exc: validation.InvalidValue) -> ProblemError:
    from app.core.errors import field_error, validation_failed

    return validation_failed([field_error(pointer, "invalid_format", str(exc))])


# Import, read --------------------------------------------------------------------------------


async def import_number(deps: ChannelDeps, principal: Principal, body: PhoneNumberImport) -> dict[str, Any]:
    host, port, transport = validation.parse_termination(body.termination_address, body.transport)
    await check_webhook_url(deps.settings, body.inbound_webhook_url)
    now = datetime.now(UTC)
    number_id = new_id("num")
    async with deps.db.transaction(workspace_id=principal.workspace_id, user_id=principal.user_id) as s:
        await require_published(
            s, {"inbound_agent_id": body.inbound_agent_id, "outbound_agent_id": body.outbound_agent_id}
        )
        await _refuse_taken(s, body.e164)
        number = PhoneNumber(
            id=number_id,
            workspace_id=principal.workspace_id,
            e164=body.e164,
            label=body.label,
            termination_host=host,
            termination_port=port,
            transport=transport,
            auth_username=body.auth_username or None,
            inbound_allowed_cidrs=list(body.inbound_allowed_cidrs),
            inbound_agent_id=body.inbound_agent_id,
            outbound_agent_id=body.outbound_agent_id,
            inbound_webhook_url=body.inbound_webhook_url,
            status="provisioning",
            created_at=now,
            updated_at=now,
        )
        s.add(number)
        try:
            await s.flush()
        except IntegrityError:
            raise _taken() from None
        if body.auth_password:
            number.auth_password_secret = PASSWORD_SECRET.format(id=number_id)
            await put_secret(
                s, deps.wrapper, principal.workspace_id, number.auth_password_secret, body.auth_password
            )
    return await _provision_and_store(deps, principal.workspace_id, number_id, body.auth_password)


def _taken() -> ProblemError:
    return conflict(
        "number_already_registered",
        "This number is already connected to Callwright. Remove it there first, or contact support.",
    )


async def _refuse_taken(session: AsyncSession, e164: str) -> None:
    from sqlalchemy import text

    status = (
        await session.execute(text("select phone_number_e164_status(:e)"), {"e": e164})
    ).scalar_one_or_none()
    if status == "draining":
        raise conflict(
            "number_being_deleted",
            "This number is being deleted after its last call. Import it again once that finishes.",
        )
    if status is not None:
        raise _taken()


async def _provision_and_store(
    deps: ChannelDeps, workspace_id: str, number_id: str, password: str | None
) -> dict[str, Any]:
    async with deps.db.transaction(workspace_id=workspace_id) as s:
        number = await _load(s, number_id)
        if password is None:
            password = await _password(deps, s, number)
    result = await provisioning.provision(
        deps.sip, number, password, agent_name=deps.settings.worker_agent_name
    )
    async with deps.db.transaction(workspace_id=workspace_id) as s:
        number = await _load(s, number_id, lock=True)
        _apply_result(number, result, datetime.now(UTC))
        await s.flush()
        return await _out(deps, s, number)


async def list_numbers(
    deps: ChannelDeps, workspace_id: str, *, page: int, page_size: int, status: str | None
) -> dict[str, Any]:
    async with deps.db.transaction(workspace_id=workspace_id) as s:
        query = select(PhoneNumber).where(PhoneNumber.deleted_at.is_(None))
        if status:
            query = query.where(PhoneNumber.status == status)
        total = int((await s.execute(select(func.count()).select_from(query.subquery()))).scalar_one())
        rows = list(
            (
                await s.execute(
                    query.order_by(PhoneNumber.created_at.desc(), PhoneNumber.id.desc())
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                )
            ).scalars()
        )
        counts = await active_counts(s, Call.phone_number_id, [n.id for n in rows])
    return {
        "items": [to_out(deps, n, counts.get(n.id, 0)) for n in rows],
        **page_meta(total, page, page_size),
    }


async def get_number(deps: ChannelDeps, workspace_id: str, number_id: str) -> dict[str, Any]:
    async with deps.db.transaction(workspace_id=workspace_id) as s:
        return await _out(deps, s, await _load(s, number_id))


async def retry_provisioning(deps: ChannelDeps, workspace_id: str, number_id: str) -> dict[str, Any]:
    async with deps.db.transaction(workspace_id=workspace_id) as s:
        number = await _load(s, number_id, lock=True)
        if number.status != "error":
            raise conflict("number_not_in_error", "Only a number whose setup failed can be retried.")
        number.status = "provisioning"
        number.updated_at = datetime.now(UTC)
    return await _provision_and_store(deps, workspace_id, number_id, None)


# Edit -------------------------------------------------------------------------------------------

_OUTBOUND_FIELDS = {
    "termination_address",
    "transport",
    "auth_username",
    "auth_password",
    "remove_auth_password",
}


async def update_number(
    deps: ChannelDeps, principal: Principal, number_id: str, body: PhoneNumberUpdate
) -> dict[str, Any]:
    fields = set(body.model_fields_set)
    if not fields:
        from app.core.errors import field_error, validation_failed

        raise validation_failed([field_error("/", "required", "Change at least one field.")])
    for name in ("label", "transport", "remove_auth_password"):
        if name in fields and getattr(body, name) is None:
            from app.core.errors import field_error, validation_failed

            raise validation_failed([field_error(f"/{name}", "required", "This field cannot be null.")])
    if "inbound_webhook_url" in fields:
        await check_webhook_url(deps.settings, body.inbound_webhook_url)
    ws = principal.workspace_id
    async with deps.db.transaction(workspace_id=ws, user_id=principal.user_id) as s:
        number = await _load(s, number_id, lock=True)
        if number.status == "draining":
            raise conflict("number_draining", "This number is being deleted; it can no longer be changed.")
        if number.status == "provisioning":
            raise conflict(
                "number_provisioning", "Setup is still running for this number. Try again shortly."
            )
        await require_published(
            s,
            {
                k: getattr(body, k)
                for k in ("inbound_agent_id", "outbound_agent_id")
                if k in fields and getattr(body, k) is not None
            },
        )
        password = await _password(deps, s, number)
        new_password = password
        if body.remove_auth_password:
            new_password = None
        if body.auth_password:
            new_password = body.auth_password
        # Apply the new values to the row (flushed only after the SIP service accepted them).
        if "label" in fields and body.label is not None:
            number.label = body.label.strip()
        if body.termination_address is not None or "transport" in fields:
            raw = (
                body.termination_address
                if body.termination_address is not None
                else number.termination_address
            )
            try:
                host, port, transport = validation.parse_termination(raw, body.transport or number.transport)
            except validation.InvalidValue as exc:
                raise _invalid("/termination_address", exc) from None
            number.termination_host, number.termination_port, number.transport = host, port, transport
        if "auth_username" in fields:
            number.auth_username = body.auth_username or None
        if "inbound_allowed_cidrs" in fields:
            number.inbound_allowed_cidrs = list(body.inbound_allowed_cidrs or [])
        if "inbound_webhook_url" in fields:
            number.inbound_webhook_url = body.inbound_webhook_url
        if "outbound_agent_id" in fields:
            number.outbound_agent_id = body.outbound_agent_id
        old_agent = number.inbound_agent_id
        if "inbound_agent_id" in fields:
            number.inbound_agent_id = body.inbound_agent_id
        if number.status == "active":
            await _sync_routing(
                deps,
                number,
                new_password,
                inbound_changed="inbound_allowed_cidrs" in fields,
                outbound_changed=bool(fields & _OUTBOUND_FIELDS),
                attach=old_agent is None and number.inbound_agent_id is not None,
                detach=old_agent is not None and number.inbound_agent_id is None,
            )
        secret_name = PASSWORD_SECRET.format(id=number.id)
        if body.auth_password:
            await put_secret(s, deps.wrapper, ws, secret_name, body.auth_password)
            number.auth_password_secret = secret_name
        elif body.remove_auth_password and number.auth_password_secret:
            await delete_secret(s, ws, number.auth_password_secret)
            number.auth_password_secret = None
        number.updated_at = datetime.now(UTC)
        await s.flush()
        return await _out(deps, s, number)


async def _sync_routing(
    deps: ChannelDeps,
    number: PhoneNumber,
    password: str | None,
    *,
    inbound_changed: bool,
    outbound_changed: bool,
    attach: bool,
    detach: bool,
) -> None:
    """SIP changes for an edit; raises 502 ``routing_update_failed`` with nothing changed."""
    sip = deps.sip
    agent_name = deps.settings.worker_agent_name
    created_rule: str | None = None
    try:
        old_inbound = number.lk_inbound_trunk_id
        inbound_id, outbound_id = await provisioning.update_trunks(
            sip, number, password, inbound_changed=inbound_changed, outbound_changed=outbound_changed
        )
        number.lk_inbound_trunk_id, number.lk_outbound_trunk_id = inbound_id, outbound_id
        replaced_inbound = inbound_id != old_inbound
        if number.inbound_agent_id and (attach or (replaced_inbound and number.lk_dispatch_rule_id)):
            created_rule = await provisioning.attach_rule(sip, number, agent_name=agent_name)
            old_rule, number.lk_dispatch_rule_id = number.lk_dispatch_rule_id, created_rule
            if old_rule:
                await _quiet(sip.delete_dispatch_rule(old_rule))
        if detach and number.lk_dispatch_rule_id:
            await sip.delete_dispatch_rule(number.lk_dispatch_rule_id)
            number.lk_dispatch_rule_id = None
    except SipError as exc:
        if created_rule:
            await _quiet(sip.delete_dispatch_rule(created_rule))
        raise ProblemError(
            502,
            "routing_update_failed",
            "Routing update failed",
            f"Nothing was changed. {exc}",
        ) from None


async def _quiet(coro: Any) -> None:
    try:
        await coro
    except SipError:
        logger.warning("SIP cleanup failed", exc_info=True)


# Delete -----------------------------------------------------------------------------------------


async def delete_number(
    deps: ChannelDeps, workspace_id: str, number_id: str, *, when_idle: bool
) -> tuple[int, dict[str, Any] | None]:
    """``(204, None)`` when deleted, ``(202, number)`` when draining."""
    async with deps.db.transaction(workspace_id=workspace_id) as s:
        number = await _load(s, number_id, lock=True)
        active = (await active_counts(s, Call.phone_number_id, [number.id])).get(number.id, 0)
        if number.status == "draining":
            return 202, to_out(deps, number, active)
        if active and not when_idle:
            raise ProblemError(
                409,
                "number_has_active_calls",
                "Number has active calls",
                f"{active} call(s) are using this number. Delete when idle to remove it after they end.",
                extra={"active_call_count": active},
            )
        if number.lk_dispatch_rule_id:
            try:
                await deps.sip.delete_dispatch_rule(number.lk_dispatch_rule_id)
                number.lk_dispatch_rule_id = None
            except SipError as exc:
                raise ProblemError(502, "routing_update_failed", "Routing update failed", str(exc)) from None
        number.updated_at = datetime.now(UTC)
        if active:
            number.status = "draining"
            await s.flush()
            return 202, to_out(deps, number, active)
        try:
            await provisioning.remove_all(deps.sip, number)
        except SipError as exc:
            # The drain cron retries the trunk removal; new calls are already refused.
            number.status = "draining"
            number.status_detail = f"Cleanup pending: {exc}"[:500]
            await s.flush()
            return 202, to_out(deps, number, 0)
        await finish_delete(s, number)
    return 204, None


async def finish_delete(session: AsyncSession, number: PhoneNumber) -> None:
    now = datetime.now(UTC)
    if number.auth_password_secret:
        await delete_secret(session, number.workspace_id, number.auth_password_secret)
        number.auth_password_secret = None
    number.status = "deleted"
    number.deleted_at = now
    number.updated_at = now
    number.lk_dispatch_rule_id = number.lk_inbound_trunk_id = number.lk_outbound_trunk_id = None
    await session.flush()


# Agent deletion (002 hook) ------------------------------------------------------------------------


async def attachments_for_agent(ctx: agent_hooks.UsageContext) -> list[agent_hooks.Attachment]:
    rows = (
        await ctx.session.execute(
            select(PhoneNumber).where(
                PhoneNumber.deleted_at.is_(None),
                or_(
                    PhoneNumber.inbound_agent_id == ctx.agent_id,
                    PhoneNumber.outbound_agent_id == ctx.agent_id,
                ),
            )
        )
    ).scalars()
    out = []
    for number in rows:
        directions = [
            d
            for d, agent in (("inbound", number.inbound_agent_id), ("outbound", number.outbound_agent_id))
            if agent == ctx.agent_id
        ]
        out.append(
            agent_hooks.Attachment(
                kind="phone_number",
                id=number.id,
                label=f"{number.label} ({number.e164}, {' and '.join(directions)})",
            )
        )
    return out
