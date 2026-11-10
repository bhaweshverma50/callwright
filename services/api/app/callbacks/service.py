"""Scheduled callbacks (011).

A callback is an outbound call booked for later, by the agent during a phone call
(``book_from_call``, the ``schedule_callback`` tool) or by a client (``create``). Booking runs
010's ``OUTBOUND_POLICIES`` with the calling hours checked at the booked time, so a time outside
the workspace's calling hours (or a do-not-call destination) is refused with the next allowed
time rather than moved silently: the caller agreed to a time, and only they can agree to another
one. 010 refuses rather than queues outside the window too (research R9).

``place_due`` (cron, every minute) dials due callbacks through ``outbound.place``: the same
policies again at dial time (blocks are logged as policy decisions), then 003 admission (credit,
concurrency, configuration) with the idempotency key ``callback:<id>``, so a callback dials at most
once even when a run dies mid-dial and the row is retried. A full workspace (concurrency limit)
waits for the next run; a callback not placed within ``MISSED_AFTER`` of its time fails as
``missed`` instead of ringing someone hours late. Every other refusal fails the callback with
its code.

Status flow: ``scheduled`` -> ``placing`` -> ``placed`` | ``failed``; ``scheduled`` -> ``cancelled``.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from callwright_contract.calls import PHONE_CHANNELS
from callwright_contract.protocol import CallbackRequest
from callwright_contract.values import CALLBACK_NOT_A_PHONE_CALL, CallbackRefusal, spoken_time
from callwright_contract.variables import BUILTIN_VARIABLES, CALLBACK_NOTE
from pydantic import ValidationError
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.models import Agent
from app.agents.variables import MAX_VALUE_CHARS
from app.callbacks.models import ScheduledCallback
from app.callbacks.schemas import (
    MAX_CARRIED_VARIABLES,
    CallbackCreate,
    parse_local,
)
from app.calls.lookups import concurrency_full
from app.calls.models import Call
from app.calls.origins import policy
from app.core.db import Database
from app.core.errors import ProblemError, field_error, not_found
from app.core.ids import new_id
from app.core.pagination import page_meta, page_window
from app.outbound import calling_hours
from app.outbound import service as outbound
from app.outbound.schemas import OutboundCallRequest

logger = logging.getLogger(__name__)

MIN_LEAD = timedelta(minutes=1)
MAX_AHEAD = timedelta(days=30)
MISSED_AFTER = timedelta(minutes=30)
DUE_BATCH = 50


def _local(instant: datetime, zone: str) -> datetime:
    return instant.astimezone(ZoneInfo(zone))


def _iso(value: datetime | None) -> str | None:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z") if value else None


def _time_problem(at: datetime, now: datetime) -> str | None:
    if at < now + MIN_LEAD:
        return "That time has already passed. Ask the caller for a time later than now."
    if at > now + MAX_AHEAD:
        return "Callbacks can be booked at most 30 days ahead. Ask the caller for an earlier time."
    return None


def to_out(row: ScheduledCallback, agent_name: str | None) -> dict[str, Any]:
    local = _local(row.scheduled_at, row.timezone).replace(tzinfo=None)
    return {
        "id": row.id,
        "status": row.status,
        "scheduled_at": _iso(row.scheduled_at),
        "timezone": row.timezone,
        "local_time": local.isoformat(timespec="seconds"),
        "to_number": row.to_number,
        "from_number": row.from_number,
        "phone_number_id": row.phone_number_id,
        "agent_id": row.agent_id,
        "agent_name": agent_name,
        "note": row.note,
        "source_call_id": row.source_call_id,
        "call_id": row.call_id,
        "created_via": row.created_via,
        "created_by_user_id": row.created_by_user_id,
        "dynamic_variables": {k: str(v) for k, v in (row.dynamic_variables or {}).items()},
        "failure_reason": row.failure_reason,
        "failure_detail": row.failure_detail,
        "attempts": row.attempts,
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
        "placed_at": _iso(row.placed_at),
        "cancelled_at": _iso(row.cancelled_at),
    }


async def _agent_name(session: AsyncSession, agent_id: str | None) -> str | None:
    if agent_id is None:
        return None
    return (await session.execute(select(Agent.name).where(Agent.id == agent_id))).scalar_one_or_none()


async def list_callbacks(
    session: AsyncSession,
    *,
    page: int,
    page_size: int,
    status: str | None,
    source_call_id: str | None,
) -> dict[str, Any]:
    query = select(ScheduledCallback, Agent.name).outerjoin(Agent, Agent.id == ScheduledCallback.agent_id)
    if status:
        query = query.where(ScheduledCallback.status == status)
    if source_call_id:
        query = query.where(ScheduledCallback.source_call_id == source_call_id)
    total = int((await session.execute(select(func.count()).select_from(query.subquery()))).scalar_one())
    order = (
        (ScheduledCallback.scheduled_at.asc(), ScheduledCallback.id.asc())
        if status == "scheduled"
        else (ScheduledCallback.scheduled_at.desc(), ScheduledCallback.id.desc())
    )
    rows = (await session.execute(query.order_by(*order).slice(*page_window(page, page_size)))).all()
    return {"items": [to_out(row, name) for row, name in rows], **page_meta(total, page, page_size)}


async def get_callback(session: AsyncSession, callback_id: str) -> dict[str, Any]:
    row = await session.get(ScheduledCallback, callback_id)
    if row is None:
        raise not_found("callback")
    return to_out(row, await _agent_name(session, row.agent_id))


async def cancel(session: AsyncSession, callback_id: str, now: datetime | None = None) -> dict[str, Any]:
    row = await session.get(ScheduledCallback, callback_id, with_for_update=True)
    if row is None:
        raise not_found("callback")
    if row.status != "cancelled":
        if row.status != "scheduled":
            raise ProblemError(
                409,
                "callback_not_scheduled",
                "Callback is not scheduled",
                f"This callback is {row.status} and can no longer be cancelled.",
            )
        stamp = now or datetime.now(UTC)
        row.status, row.cancelled_at, row.updated_at = "cancelled", stamp, stamp
        await session.flush()
    return to_out(row, await _agent_name(session, row.agent_id))


def _carried(values: Mapping[str, Any], note: str) -> dict[str, str]:
    carried = {
        k: str(v)[:MAX_VALUE_CHARS]
        for k, v in values.items()
        if k not in BUILTIN_VARIABLES and k != CALLBACK_NOTE
    }
    kept = dict(list(carried.items())[:MAX_CARRIED_VARIABLES])
    kept[CALLBACK_NOTE] = note
    return kept


async def create(
    db: Database, workspace_id: str, user_id: str, body: CallbackCreate, now: datetime | None = None
) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    at = body.scheduled_at.astimezone(UTC)
    problem = _time_problem(at, now)
    if problem:
        raise ProblemError(
            422,
            "invalid_time",
            "Invalid time",
            problem,
            errors=[
                field_error("/scheduled_at", "out_of_range", "Use a time from one minute to 30 days ahead.")
            ],
        )
    request = OutboundCallRequest(
        to_number=body.to_number,
        from_number=body.from_number,
        agent_id=body.agent_id,
        dynamic_variables=_carried(body.dynamic_variables, body.note),
        recipient_timezone=body.recipient_timezone,
    )
    zones, source = outbound.zones_for(request)
    callback_id = new_id("cbk")
    requester = outbound.Requester(workspace_id, user_id, user_id)
    async with db.transaction(workspace_id=workspace_id, user_id=user_id) as session:
        try:
            ctx = await outbound.check_policies(session, requester, request, callback_id, zones, source, at)
        except outbound.PolicyBlocked as blocked:
            raise blocked.problem from None
        assert ctx.number is not None and ctx.agent_id is not None
        row = ScheduledCallback(
            id=callback_id,
            workspace_id=workspace_id,
            phone_number_id=ctx.number.id,
            from_number=request.from_number,
            to_number=request.to_number,
            agent_id=ctx.agent_id,
            scheduled_at=at,
            timezone=zones[0],
            recipient_timezones=zones,
            timezone_source=source,
            note=body.note,
            dynamic_variables=dict(request.dynamic_variables),
            created_via="api",
            created_by_user_id=user_id,
            status="scheduled",
            attempts=0,
            created_at=now,
            updated_at=now,
        )
        session.add(row)
        await session.flush()
        return to_out(row, await _agent_name(session, row.agent_id))


def refused(reason: CallbackRefusal, detail: str, **extra: Any) -> ProblemError:
    return ProblemError(
        422, "callback_not_possible", "Callback not possible", detail, extra={"reason": reason, **extra}
    )


@dataclass(frozen=True)
class Recipient:
    to_number: str
    from_number: str
    zones: list[str]
    source: str
    timezone: str


def _call_zone(call: Call) -> str | None:
    values = call.dynamic_variables or {}
    zone = values.get("timezone") if isinstance(values, Mapping) else None
    if not isinstance(zone, str) or not zone:
        return None
    try:
        return calling_hours.check_timezone(zone)
    except calling_hours.InvalidTimezone:
        return None


def recipient_of(call: Call) -> Recipient:
    """Who to call back and from which number: the caller on inbound calls, the dialled number
    on outbound calls; the zone is the one the call ran in (its ``timezone`` variable) when the
    number allows it, otherwise the number's zones."""
    if call.direction == "inbound":
        to_number, from_number = call.from_number, call.to_number
    else:
        to_number, from_number = call.to_number, call.from_number
    if not to_number or not from_number or not call.phone_number_id:
        raise refused(
            "number_unavailable",
            "The caller's number is not available on this call, so a callback cannot be booked.",
        )
    derived, _ = calling_hours.recipient_zones(to_number, None)
    zone = _call_zone(call)
    if derived and (zone in derived or zone in (None, "UTC")):
        return Recipient(
            to_number, from_number, derived, "number_region", zone if zone in derived else derived[0]
        )
    if zone and zone != "UTC":
        return Recipient(to_number, from_number, [zone], "override", zone)
    raise refused(
        "unknown_timezone",
        "The caller's timezone is unknown, so a callback time cannot be booked safely.",
    )


def resolve_time(body: CallbackRequest, zone: str, now: datetime) -> datetime:
    if body.in_minutes is not None:
        return (now + timedelta(minutes=body.in_minutes)).replace(second=0, microsecond=0)
    try:
        parsed = parse_local(body.at or "")
    except ValueError:
        raise refused(
            "invalid_time",
            "That time could not be read. Pass the local date and time like 2026-11-04T17:00.",
        ) from None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo(zone))
    return parsed.astimezone(UTC)


def _booked(
    callback_id: str | None,
    at: datetime,
    zone: str,
    now: datetime,
    *,
    mocked: bool,
    rescheduled: bool,
) -> dict[str, Any]:
    local = _local(at, zone)
    return {
        "scheduled": True,
        "mocked": mocked,
        "callback_id": callback_id,
        "scheduled_at": _iso(at),
        "timezone": zone,
        "local_time": local.replace(tzinfo=None).isoformat(timespec="minutes"),
        "spoken_time": spoken_time(local, _local(now, zone)),
        "rescheduled": rescheduled,
    }


def _policy_refusal(exc: Exception, zone: str, now: datetime) -> ProblemError:
    if isinstance(exc, outbound.PolicyBlocked):
        if exc.reason == "dnc_listed":
            return refused(
                "dnc_listed",
                "This number is on the do-not-call list, so a callback cannot be booked. Do not promise one.",
            )
        next_at = exc.decision.get("next_allowed_at")
        if isinstance(next_at, datetime):
            spoken = spoken_time(_local(next_at, zone), _local(now, zone))
            return refused(
                "outside_calling_hours",
                f"That time is outside the calling hours for this number. The earliest allowed "
                f"time after it is {spoken}. Offer that time or another time within calling hours.",
                next_allowed_at=_iso(next_at),
                next_allowed_spoken=spoken,
            )
        return refused(
            "outside_calling_hours",
            "That time is outside the calling hours for this number. Ask for another time.",
            next_allowed_at=None,
            next_allowed_spoken=None,
        )
    assert isinstance(exc, ProblemError)
    if exc.code in ("no_outbound_agent", "agent_not_published") or any(
        e.get("pointer") == "/agent_id" for e in exc.errors or []
    ):
        return refused("agent_unavailable", "Callbacks are not available for this agent right now.")
    return refused(
        "number_unavailable",
        "The number this call uses cannot place calls right now, so a callback cannot be booked.",
    )


async def book_from_call(
    db: Database, workspace_id: str, call_id: str, body: CallbackRequest, now: datetime | None = None
) -> tuple[int, dict[str, Any]]:
    now = now or datetime.now(UTC)
    async with db.transaction(workspace_id=workspace_id) as session:
        call = await session.get(Call, call_id)
        if call is None:
            raise not_found("call")
        if not policy(call.origin).reaches_customer:
            # 008: simulations never reach customers; answer as if booked, store nothing.
            zone = _call_zone(call) or "UTC"
            at = resolve_time(body, zone, now)
            problem = _time_problem(at, now)
            if problem:
                raise refused("invalid_time", problem)
            return 200, _booked(None, at, zone, now, mocked=True, rescheduled=False)
        if call.channel not in PHONE_CHANNELS:
            raise refused("channel_unsupported", CALLBACK_NOT_A_PHONE_CALL)
        recipient = recipient_of(call)
        at = resolve_time(body, recipient.timezone, now)
        problem = _time_problem(at, now)
        if problem:
            raise refused("invalid_time", problem)
        try:
            request = OutboundCallRequest(
                to_number=recipient.to_number,
                from_number=recipient.from_number,
                agent_id=call.agent_id,
                dynamic_variables=_carried(call.dynamic_variables or {}, body.note),
                recipient_timezone=recipient.timezone if recipient.source == "override" else None,
            )
        except ValidationError:
            raise refused(
                "number_unavailable",
                "The caller's number cannot be called back, so a callback cannot be booked.",
            ) from None
        requester = outbound.Requester(workspace_id, None, "agent")
        try:
            ctx = await outbound.check_policies(
                session, requester, request, call_id, recipient.zones, recipient.source, at
            )
        except (outbound.PolicyBlocked, ProblemError) as exc:
            raise _policy_refusal(exc, recipient.timezone, now) from None
        assert ctx.number is not None and ctx.agent_id is not None
        existing = (
            await session.execute(
                select(ScheduledCallback)
                .where(
                    ScheduledCallback.source_call_id == call_id,
                    ScheduledCallback.status == "scheduled",
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        row = existing or ScheduledCallback(
            id=new_id("cbk"),
            workspace_id=workspace_id,
            source_call_id=call_id,
            created_via="agent",
            status="scheduled",
            attempts=0,
            created_at=now,
        )
        row.phone_number_id = ctx.number.id
        row.from_number = request.from_number
        row.to_number = request.to_number
        row.agent_id = ctx.agent_id
        row.scheduled_at = at
        row.timezone = recipient.timezone
        row.recipient_timezones = recipient.zones
        row.timezone_source = recipient.source
        row.note = body.note
        row.dynamic_variables = dict(request.dynamic_variables)
        row.updated_at = now
        if existing is None:
            session.add(row)
        await session.flush()
        return 201, _booked(
            row.id, at, recipient.timezone, now, mocked=False, rescheduled=existing is not None
        )


def _fail(row: ScheduledCallback, reason: str, detail: str | None, now: datetime) -> None:
    row.status = "failed"
    row.failure_reason = reason[:64]
    row.failure_detail = (detail or "")[:500] or None
    row.updated_at = now


def _request_for(row: ScheduledCallback) -> OutboundCallRequest:
    return OutboundCallRequest(
        to_number=row.to_number,
        from_number=row.from_number,
        agent_id=row.agent_id,
        dynamic_variables={k: str(v) for k, v in (row.dynamic_variables or {}).items()},
        metadata={
            "callback_id": row.id,
            **({"source_call_id": row.source_call_id} if row.source_call_id else {}),
        },
        recipient_timezone=row.timezone if row.timezone_source == "override" else None,
    )


async def _finish(
    db: Database,
    workspace_id: str,
    callback_id: str,
    *,
    call_id: str | None,
    reason: str | None = None,
    detail: str | None = None,
) -> None:
    now = datetime.now(UTC)
    async with db.transaction(workspace_id=workspace_id) as session:
        row = await session.get(ScheduledCallback, callback_id, with_for_update=True)
        if row is None or row.status != "placing":
            return
        row.call_id = call_id or row.call_id
        if reason is None:
            row.status, row.placed_at, row.updated_at = "placed", now, now
        else:
            _fail(row, reason, detail, now)


async def place_one(deps: outbound.OutboundDeps, workspace_id: str, callback_id: str, now: datetime) -> str:
    """Claim and dial one due callback; returns the resulting status (or ``skipped``)."""
    async with deps.db.transaction(workspace_id=workspace_id) as session:
        row = (
            await session.execute(
                select(ScheduledCallback)
                .where(ScheduledCallback.id == callback_id)
                .with_for_update(skip_locked=True)
            )
        ).scalar_one_or_none()
        if row is None or row.status not in ("scheduled", "placing") or row.scheduled_at > now:
            return "skipped"
        if now - row.scheduled_at > MISSED_AFTER:
            _fail(row, "missed", "The callback could not be placed within 30 minutes of its time.", now)
            return "failed"
        if deps.settings.livekit_mode == "live" and not deps.sip.live:
            _fail(row, "telephony_unavailable", "This deployment has no SIP service.", now)
            return "failed"
        if row.status == "scheduled" and await concurrency_full(session, workspace_id):
            return "skipped"  # every call slot is busy: the next run tries again
        row.status, row.attempts, row.updated_at = "placing", row.attempts + 1, now
        request = _request_for(row)
    key = f"callback:{callback_id}"
    try:
        zones, source = outbound.zones_for(request)
        _, result = await outbound.place(
            deps, outbound.Requester(workspace_id, None, key), request, key, zones, source
        )
    except outbound.PolicyBlocked as blocked:
        await outbound.record_block(deps, blocked)
        await _finish(
            deps.db,
            workspace_id,
            callback_id,
            call_id=None,
            reason=blocked.reason,
            detail=blocked.problem.detail,
        )
        return "failed"
    except ProblemError as problem:
        call_id = problem.extra.get("call_id")
        await _finish(
            deps.db,
            workspace_id,
            callback_id,
            call_id=call_id if isinstance(call_id, str) else None,
            reason=problem.code,
            detail=problem.detail or problem.title,
        )
        return "failed"
    except Exception:
        # Left in placing: callbacks_due hands it back after 2 minutes and the idempotency key
        # stops a second dial.
        logger.exception("placing callback %s failed", callback_id)
        return "error"
    await _finish(deps.db, workspace_id, callback_id, call_id=str(result["call_id"]))
    return "placed"


async def place_due(deps: outbound.OutboundDeps, now: datetime | None = None, limit: int = DUE_BATCH) -> int:
    """Dial every due callback (any workspace); returns how many were placed."""
    now = now or datetime.now(UTC)
    async with deps.db.transaction() as session:
        rows = (
            await session.execute(
                text("select id, workspace_id from callbacks_due(:now, :limit)"), {"now": now, "limit": limit}
            )
        ).all()
    placed = 0
    for row in rows:
        if await place_one(deps, str(row.workspace_id), str(row.id), now) == "placed":
            placed += 1
    if rows:
        logger.info("callbacks: %d due, %d placed", len(rows), placed)
    return placed
