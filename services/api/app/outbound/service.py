"""Outbound calls (010 T030, T032, T068, T077, research R6, R7, R9).

``POST /v1/outbound-calls`` runs, in order: telephony availability, the per-workspace token
bucket (10 per second, burst 20), the Idempotency-Key claim, then ``OUTBOUND_POLICIES``
(``same_number``, ``number_active``, ``agent_published``, ``dnc_listed``,
``outside_calling_hours``; the first failure wins), then 003's ``admit()`` with channel
``sip_outbound``, room ``call-{call_id}`` and a worker dispatch with ``{"call_id"}``.

Compliance blocks (``dnc_listed``, ``outside_calling_hours``) never reach ``admit()``: no call
row, no dispatch, no charge. Each writes one ``outbound_policy_decisions`` row in its own
transaction and releases the Idempotency-Key, so a retry with the same key is evaluated afresh.
Every other outcome (success or problem) is stored against the key and replayed for 24 hours;
a replayed success carries ``idempotent_replay: true``. The unique
``calls(workspace_id, idempotency_key)`` index is the second guard against double dialling.

``SipOutboundDial`` is the ``OutboundDialProvider`` 003 calls at claim time: the number's
outbound trunk, the two numbers and the ring timeout stored on the call.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from fastapi.responses import JSONResponse
from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.calls import service as calls
from app.calls.catalog import AdapterCatalog
from app.calls.effects import Deferred, dispatch
from app.calls.models import Call
from app.calls.ports import OutboundDial
from app.core import idempotency
from app.core.auth import Principal
from app.core.errors import ProblemError, field_error, too_many_requests, validation_failed
from app.core.livekit import LiveKitError, LiveKitGateway
from app.core.pagination import page_meta
from app.core.queue import JobQueue
from app.core.rate_limit import TokenBucket
from app.outbound import calling_hours, dnc
from app.outbound.models import OutboundCallingHours, OutboundPolicyDecision
from app.outbound.schemas import OutboundCallRequest
from app.phone_numbers.models import PhoneNumber
from app.phone_numbers.shared import ChannelDeps, agent_state, conflict

logger = logging.getLogger(__name__)

ENDPOINT = "POST /v1/outbound-calls"


@dataclass
class OutboundDeps(ChannelDeps):
    livekit: LiveKitGateway | None = None
    catalog: AdapterCatalog | None = None
    jobs: JobQueue | None = None
    redis: Redis | None = None


@dataclass
class Context:
    """What the policies read and fill in."""

    principal: Principal
    body: OutboundCallRequest
    key: str
    session: AsyncSession
    now: datetime
    number: PhoneNumber | None = None
    agent_id: str | None = None
    zones: list[str] = field(default_factory=list)
    timezone_source: str | None = None


class PolicyBlocked(Exception):
    def __init__(
        self, reason: str, title: str, detail: str, extra: dict[str, Any], decision: dict[str, Any]
    ) -> None:
        super().__init__(detail)
        self.problem = ProblemError(
            422,
            "outbound_policy",
            title,
            detail,
            extra={"reason": reason, **extra},
        )
        self.reason = reason
        self.decision = decision


# Policies ---------------------------------------------------------------------------------------


async def same_number(ctx: Context) -> None:
    if ctx.body.to_number == ctx.body.from_number:
        raise ProblemError(
            422,
            "same_number",
            "Same number",
            "The destination is the number you are calling from.",
            errors=[
                field_error(
                    "/to_number", "same_number", "Call a different number from the one you call from."
                )
            ],
        )


async def number_active(ctx: Context) -> None:
    number = (
        await ctx.session.execute(
            select(PhoneNumber).where(
                PhoneNumber.e164 == ctx.body.from_number, PhoneNumber.deleted_at.is_(None)
            )
        )
    ).scalar_one_or_none()
    if number is None:
        raise validation_failed(
            [field_error("/from_number", "not_found", "This number is not imported in this workspace.")]
        )
    if number.status != "active":
        raise conflict(
            "from_number_not_active",
            f"{number.e164} is {number.status.replace('_', ' ')}; outbound calls need an active number.",
        )
    ctx.number = number


async def agent_published(ctx: Context) -> None:
    assert ctx.number is not None
    agent_id = ctx.body.agent_id or ctx.number.outbound_agent_id
    if agent_id is None:
        raise conflict(
            "no_outbound_agent",
            "Choose an agent, or attach an outbound agent to this number first.",
        )
    state = await agent_state(ctx.session, agent_id)
    if state == "missing":
        raise validation_failed(
            [field_error("/agent_id", "not_found", "No agent with that id exists in this workspace.")]
        )
    if state == "unpublished":
        raise conflict("agent_not_published", "This agent has no published version. Publish it first.")
    ctx.agent_id = agent_id


def _decision(ctx: Context, reason: str, **extra: Any) -> dict[str, Any]:
    return {
        "workspace_id": ctx.principal.workspace_id,
        "decided_at": ctx.now,
        "reason": reason,
        "to_number": ctx.body.to_number,
        "from_number": ctx.body.from_number,
        "phone_number_id": ctx.number.id if ctx.number else None,
        "agent_id": ctx.agent_id,
        "requested_by": ctx.principal.user_id,
        "idempotency_key": ctx.key,
        **extra,
    }


async def dnc_listed(ctx: Context) -> None:
    entry = await dnc.find(ctx.session, ctx.body.to_number)
    if entry is None:
        return
    raise PolicyBlocked(
        "dnc_listed",
        "Destination is on the do-not-call list",
        f"{ctx.body.to_number} is on this workspace's do-not-call list. Remove it there to call it.",
        {"to_number": ctx.body.to_number, "dnc_entry_id": entry.id},
        _decision(ctx, "dnc_listed", dnc_entry_id=entry.id, dnc_e164=entry.e164),
    )


async def outside_calling_hours(ctx: Context) -> None:
    row = await ctx.session.get(OutboundCallingHours, ctx.principal.workspace_id)
    windows = row.windows if row is not None else calling_hours.DEFAULT_WINDOWS
    result = calling_hours.evaluate(windows, ctx.zones, ctx.timezone_source or "unknown", ctx.now)
    if result.allowed:
        return
    local = result.local_time.isoformat(timespec="seconds") if result.local_time else None
    next_at = result.next_allowed_at.isoformat().replace("+00:00", "Z") if result.next_allowed_at else None
    if result.source == "unknown":
        detail = (
            "No timezone can be derived from this number. Send recipient_timezone (for example "
            "America/New_York) to place the call."
        )
    else:
        detail = (
            f"It is {local.replace('T', ' ')[:16] if local else 'now'} for the recipient "
            f"({', '.join(result.zones[:3])}{'...' if len(result.zones) > 3 else ''}), outside calling hours."
        )
    raise PolicyBlocked(
        "outside_calling_hours",
        "Outside calling hours for the recipient",
        detail,
        {
            "to_number": ctx.body.to_number,
            "recipient_timezones": result.zones,
            "timezone_source": result.source,
            "recipient_local_time": local,
            "next_allowed_at": next_at,
        },
        _decision(
            ctx,
            "outside_calling_hours",
            recipient_timezones=result.zones,
            timezone_source=result.source,
            recipient_local_time=result.local_time,
            next_allowed_at=result.next_allowed_at,
        ),
    )


Policy = Callable[[Context], Awaitable[None]]
OUTBOUND_POLICIES: list[Policy] = [
    same_number,
    number_active,
    agent_published,
    dnc_listed,
    outside_calling_hours,
]


# Request ----------------------------------------------------------------------------------------


def _zones(body: OutboundCallRequest) -> tuple[list[str], str]:
    try:
        return calling_hours.recipient_zones(body.to_number, body.recipient_timezone)
    except calling_hours.InvalidTimezone as exc:
        raise ProblemError(
            422,
            "invalid_timezone",
            "Invalid timezone",
            str(exc),
            errors=[field_error("/recipient_timezone", "invalid_timezone", str(exc))],
        ) from None


async def _record_block(deps: OutboundDeps, blocked: PolicyBlocked) -> None:
    async with deps.db.transaction(workspace_id=blocked.decision["workspace_id"]) as session:
        session.add(OutboundPolicyDecision(**blocked.decision))
    logger.info("outbound call blocked: %s", blocked.reason)


async def start_outbound_call(
    deps: OutboundDeps, principal: Principal, body: OutboundCallRequest, key: str | None, instance: str
) -> JSONResponse:
    if deps.settings.livekit_mode == "live" and not deps.sip.live:
        raise ProblemError(
            503,
            "telephony_unavailable",
            "Phone calls are not enabled",
            "This deployment has no SIP service yet, so outbound calls cannot be placed.",
        )
    key = idempotency.require_key(key)
    zones, source = _zones(body)
    assert deps.redis is not None
    bucket = TokenBucket(
        deps.redis, rate_per_s=deps.settings.outbound_rate_per_second, burst=deps.settings.outbound_rate_burst
    )
    limited = await bucket.take("outbound", principal.workspace_id)
    if not limited.allowed:
        raise too_many_requests(
            limited.retry_after_s, "More than 10 outbound calls per second. Slow down and retry."
        )
    payload = body.model_dump(mode="json")
    stored = await idempotency.claim(deps.db, principal.workspace_id, ENDPOINT, key, payload)
    if stored is not None:
        if not stored.problem and isinstance(stored.body, dict):
            return JSONResponse({**stored.body, "idempotent_replay": True}, status_code=stored.status)
        return idempotency.replay_response(stored)
    try:
        status, result = await _place(deps, principal, body, key, zones, source)
    except PolicyBlocked as blocked:
        await idempotency.release(deps.db, principal.workspace_id, ENDPOINT, key)
        await _record_block(deps, blocked)
        raise blocked.problem from None
    except ProblemError as problem:
        await idempotency.store(
            deps.db,
            principal.workspace_id,
            ENDPOINT,
            key,
            problem.status,
            problem.body(instance),
            problem=True,
        )
        raise
    except BaseException:
        await idempotency.release(deps.db, principal.workspace_id, ENDPOINT, key)
        raise
    await idempotency.store(deps.db, principal.workspace_id, ENDPOINT, key, status, result, problem=False)
    return JSONResponse(result, status_code=status)


async def _place(
    deps: OutboundDeps,
    principal: Principal,
    body: OutboundCallRequest,
    key: str,
    zones: list[str],
    source: str,
) -> tuple[int, dict[str, Any]]:
    now = datetime.now(UTC)
    async with deps.db.transaction(workspace_id=principal.workspace_id, user_id=principal.user_id) as session:
        ctx = Context(principal, body, key, session, now, zones=zones, timezone_source=source)
        for policy in OUTBOUND_POLICIES:
            await policy(ctx)
        assert ctx.number is not None and ctx.agent_id is not None
        number_id, agent_id = ctx.number.id, ctx.agent_id
    assert deps.catalog is not None and deps.livekit is not None
    admission = await calls.admit(
        deps.db,
        calls.AdmissionRequest(
            workspace_id=principal.workspace_id,
            agent_id=agent_id,
            channel="sip_outbound",
            direction="outbound",
            version="published",
            origin="live",
            variables=body.dynamic_variables,
            metadata=body.metadata,
            from_number=body.from_number,
            to_number=body.to_number,
            phone_number_id=number_id,
            initiated_by_user_id=principal.user_id,
            idempotency_key=key,
            timezone=zones[0] if zones else None,
            ring_timeout_s=body.ring_timeout_s,
        ),
        catalog=deps.catalog,
        now=now,
    )
    await dispatch(deps.jobs, admission.deferred)
    call = admission.call
    if not admission.admitted:
        assert admission.refusal is not None
        raise admission.refusal.problem(call.id)
    if admission.created:
        await _start_room(deps, call)
    assert admission.snapshot is not None
    return 202, {
        "call_id": call.id,
        "status": call.status,
        "to_number": body.to_number,
        "from_number": body.from_number,
        "agent_id": agent_id,
        "agent_version_id": admission.snapshot.version_id,
        "phone_number_id": number_id,
        "missing_variables": list(call.missing_variables or []),
        "idempotent_replay": not admission.created,
        "recipient_timezones": zones,
        "timezone_source": source,
    }


async def _start_room(deps: OutboundDeps, call: Call) -> None:
    from app.sessions.service import media_unavailable, room_name

    assert deps.livekit is not None
    room = room_name(call.id)
    try:
        await deps.livekit.create_room(room, metadata=f'{{"call_id":"{call.id}"}}')
        await deps.livekit.dispatch_agent(room, deps.settings.worker_agent_name, {"call_id": call.id})
    except LiveKitError:
        logger.exception("room setup failed for outbound call %s", call.id)
        deferred = Deferred()
        await calls.mark_failed(deps.db, call.workspace_id, call.id, "room_unavailable", deferred=deferred)
        await dispatch(deps.jobs, deferred)
        try:
            await deps.livekit.delete_room(room)
        except LiveKitError:
            logger.warning("could not delete room %s after a failed setup", room)
        raise media_unavailable(call.id) from None
    async with deps.db.transaction(workspace_id=call.workspace_id) as session:
        row = await session.get(Call, call.id)
        assert row is not None
        row.room_name = room


# Decision log -------------------------------------------------------------------------------------


def decision_out(row: OutboundPolicyDecision) -> dict[str, Any]:
    return {
        "id": row.id,
        "decided_at": row.decided_at.isoformat(),
        "reason": row.reason,
        "to_number": row.to_number,
        "from_number": row.from_number,
        "phone_number_id": row.phone_number_id,
        "agent_id": row.agent_id,
        "requested_by": row.requested_by,
        "dnc_entry_id": row.dnc_entry_id,
        "dnc_number": row.dnc_e164,
        "recipient_timezones": list(row.recipient_timezones or []),
        "timezone_source": row.timezone_source,
        "recipient_local_time": row.recipient_local_time.isoformat() if row.recipient_local_time else None,
        "next_allowed_at": row.next_allowed_at.isoformat() if row.next_allowed_at else None,
    }


async def list_decisions(
    session: AsyncSession,
    *,
    page: int,
    page_size: int,
    reason: str | None,
    to_number: str | None,
    since: datetime | None,
) -> dict[str, Any]:
    query = select(OutboundPolicyDecision)
    if reason:
        query = query.where(OutboundPolicyDecision.reason == reason)
    if to_number:
        query = query.where(OutboundPolicyDecision.to_number == to_number)
    if since:
        query = query.where(OutboundPolicyDecision.decided_at >= since)
    total = int((await session.execute(select(func.count()).select_from(query.subquery()))).scalar_one())
    rows = (
        await session.execute(
            query.order_by(OutboundPolicyDecision.decided_at.desc(), OutboundPolicyDecision.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).scalars()
    return {"items": [decision_out(r) for r in rows], **page_meta(total, page, page_size)}


# Dial provider (003 extension point) ----------------------------------------------------------------


class SipOutboundDial:
    async def dial_spec(self, session: AsyncSession, call: Any) -> OutboundDial | None:
        if not call.phone_number_id or not call.to_number or not call.from_number:
            return None
        number = await session.get(PhoneNumber, call.phone_number_id)
        if number is None or number.lk_outbound_trunk_id is None:
            return None
        return OutboundDial(
            sip_trunk_id=number.lk_outbound_trunk_id,
            to_number=call.to_number,
            from_number=call.from_number,
            ring_timeout_s=int(call.ring_timeout_s or 30),
        )
