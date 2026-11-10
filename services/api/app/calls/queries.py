"""Call read side queries (006 T015, T029, T089): list filters, sort and pagination, and the
detail, transcript, turn-latency and flow-path loaders. Every query runs in an RLS-scoped
transaction, so a call from another workspace is simply not found.

Field mapping onto 003's ``calls`` table: ``started_at`` is ``created_at``, ``duration_s`` is
``billable_seconds`` (0 until the call ends), ``latency_avg_ms`` is the stored latency summary's
``e2e_avg_ms``, and ``agent.name`` is the agent's name (agents are only soft-deleted, so the row
and its name survive; ``deleted`` marks them).
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from callwright_contract.calls import ACTIVE_STATUSES, CALL_STATUSES, CHANNELS, DISCONNECT_REASONS
from sqlalchemy import Integer, and_, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.agents.models import Agent
from app.calls.cost_view import cost_view
from app.calls.lookups import snapshot_for
from app.calls.models import Call, CallEvent
from app.calls.origins import ORIGINS
from app.calls.ports import registry
from app.calls.quality_port import EVAL_STATUSES, LABEL_FILTERS, QualitySummary
from app.calls.transcript import normalize_items, stored_items
from app.core.db import escape_like
from app.core.errors import ProblemError, field_error, validation_failed
from app.core.pagination import page_window

SENTIMENTS = ("positive", "neutral", "negative", "unknown")
SORTS = ("started_at", "duration_s", "cost_usd", "latency_avg_ms")
DEFAULT_ORIGINS = ["live", "test"]
PENDING_STATES = frozenset({"ended", "processing"})
_ID = re.compile(r"^agt_[A-Za-z0-9]+$")

LATENCY_AVG = Call.latency_stats["e2e_avg_ms"].astext.cast(Integer)


def split_csv(value: str | None, allowed: Sequence[str]) -> list[str]:
    """Comma list filtered to ``allowed`` (unknown values are dropped), in order, no repeats."""
    out: list[str] = []
    for part in (value or "").split(","):
        v = part.strip()
        if v in allowed and v not in out:
            out.append(v)
    return out


def digits(value: str | None) -> str:
    return re.sub(r"\D", "", value or "")


def _zone(tz: str | None) -> ZoneInfo:
    try:
        return ZoneInfo(tz or "UTC")
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise validation_failed(
            [field_error("/tz", "invalid_format", "Use an IANA timezone such as Asia/Kolkata.")]
        ) from exc


def _date(value: str | None, name: str) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise validation_failed(
            [field_error(f"/{name}", "invalid_format", "Use a date like 2026-10-01.")]
        ) from exc


def date_window(
    start_date: str | None, end_date: str | None, tz: str | None
) -> tuple[datetime | None, datetime | None]:
    """Calendar dates in ``tz`` to ``[start 00:00, end + 1 day 00:00)`` in UTC (FR-038)."""
    zone = _zone(tz)
    start, end = _date(start_date, "start_date"), _date(end_date, "end_date")
    if start and end and end < start:
        raise ProblemError(
            422,
            "validation_failed",
            "Request is not valid",
            "End date must be on or after start date.",
            errors=[field_error("/end_date", "out_of_range", "End date must be on or after start date.")],
        )

    def midnight(d: date) -> datetime:
        return datetime(d.year, d.month, d.day, tzinfo=zone).astimezone(UTC)

    return (midnight(start) if start else None, midnight(end + timedelta(days=1)) if end else None)


def _instant(value: str | None, name: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise validation_failed(
            [field_error(f"/{name}", "invalid_format", "Use an ISO 8601 date-time.")]
        ) from exc
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


@dataclass
class CallListQuery:
    sort: str = "started_at"
    order: str = "desc"
    call_id: str | None = None
    agent_ids: list[str] = field(default_factory=list)
    statuses: list[str] = field(default_factory=list)
    channels: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    sentiments: list[str] = field(default_factory=list)
    from_digits: str | None = None
    to_digits: str | None = None
    started_after: datetime | None = None
    started_before: datetime | None = None
    window_from: datetime | None = None
    window_to: datetime | None = None
    labels: list[str] = field(default_factory=list)
    eval_statuses: list[str] = field(default_factory=list)
    origins: list[str] = field(default_factory=lambda: list(DEFAULT_ORIGINS))


def parse_list_query(params: Mapping[str, str | None]) -> CallListQuery:
    sort = params.get("sort") or "started_at"
    order = params.get("order") or "desc"
    if sort not in SORTS:
        raise validation_failed(
            [field_error("/sort", "not_in_catalog", f"Sort by one of {', '.join(SORTS)}.")]
        )
    if order not in ("asc", "desc"):
        raise validation_failed([field_error("/order", "not_in_catalog", "Order is asc or desc.")])
    call_id = (params.get("call_id") or "").strip() or None
    if call_id is not None and len(call_id) < 8:
        raise validation_failed(
            [field_error("/call_id", "out_of_range", "Type at least 8 characters of the call ID.")]
        )
    agent_ids: list[str] = []
    for part in (params.get("agent_id") or "").split(","):
        v = part.strip()
        if _ID.match(v) and v not in agent_ids:
            agent_ids.append(v)
    window_from, window_to = date_window(params.get("start_date"), params.get("end_date"), params.get("tz"))
    return CallListQuery(
        sort=sort,
        order=order,
        call_id=call_id,
        agent_ids=agent_ids,
        statuses=split_csv(params.get("status"), CALL_STATUSES),
        channels=split_csv(params.get("channel"), CHANNELS),
        reasons=split_csv(params.get("disconnect_reason"), DISCONNECT_REASONS),
        sentiments=split_csv(params.get("sentiment"), SENTIMENTS),
        from_digits=digits(params.get("from_number")) or None,
        to_digits=digits(params.get("to_number")) or None,
        started_after=_instant(params.get("started_after"), "started_after"),
        started_before=_instant(params.get("started_before"), "started_before"),
        window_from=window_from,
        window_to=window_to,
        labels=split_csv(params.get("label"), LABEL_FILTERS),
        eval_statuses=split_csv(params.get("eval_status"), EVAL_STATUSES),
        origins=split_csv(params.get("origin"), ORIGINS) or list(DEFAULT_ORIGINS),
    )


def _like_prefix(value: str) -> str:
    return escape_like(value) + "%"


def conditions(q: CallListQuery, user_id: str) -> list[ColumnElement[bool]]:
    """AND across filters, OR (``IN``) within one."""
    where: list[ColumnElement[bool]] = [Call.origin.in_(q.origins)]
    if q.call_id:
        where.append(or_(Call.id == q.call_id, Call.id.like(_like_prefix(q.call_id), escape="\\")))
    if q.agent_ids:
        where.append(Call.agent_id.in_(q.agent_ids))
    if q.statuses:
        where.append(Call.status.in_(q.statuses))
    if q.channels:
        where.append(Call.channel.in_(q.channels))
    if q.reasons:
        where.append(Call.disconnect_reason.in_(q.reasons))
    if q.sentiments:
        known = [s for s in q.sentiments if s != "unknown"]
        parts: list[ColumnElement[bool]] = [Call.sentiment.in_(known)] if known else []
        if "unknown" in q.sentiments:
            parts.append(or_(Call.sentiment.is_(None), Call.sentiment == "unknown"))
        where.append(or_(*parts))
    for column, value in ((Call.from_number, q.from_digits), (Call.to_number, q.to_digits)):
        if value:
            where.append(func.regexp_replace(column, r"\D", "", "g").like(value + "%"))
    for lower in (q.started_after, q.window_from):
        if lower is not None:
            where.append(Call.created_at >= lower)
    if q.started_before is not None:
        where.append(Call.created_at <= q.started_before)
    if q.window_to is not None:
        where.append(Call.created_at < q.window_to)
    if q.labels or q.eval_statuses:
        where.append(
            registry.quality.filter_clause(
                Call.id, labels=q.labels, eval_statuses=q.eval_statuses, user_id=user_id
            )
        )
    return where


def _order(q: CallListQuery) -> list[Any]:
    column: Any = {
        "started_at": Call.created_at,
        "duration_s": func.coalesce(Call.billable_seconds, 0),
        "cost_usd": Call.cost_total_usd,
        "latency_avg_ms": LATENCY_AVG,
    }[q.sort]
    primary = column.asc().nulls_last() if q.order == "asc" else column.desc().nulls_last()
    tie = Call.id.asc() if q.order == "asc" else Call.id.desc()
    return [primary, tie]


def _base() -> Any:
    return select(Call, Agent.name, Agent.deleted_at).outerjoin(Agent, Agent.id == Call.agent_id)


def list_item(
    call: Call,
    agent_name: str | None,
    agent_deleted: datetime | None,
    quality: QualitySummary,
    analysis: tuple[str, str | None] | None = None,
) -> dict[str, Any]:
    pending = call.status in PENDING_STATES
    return {
        "call_id": call.id,
        "started_at": call.created_at.isoformat(),
        "agent": {
            "id": call.agent_id,
            "name": agent_name or "Unknown agent",
            "deleted": agent_deleted is not None,
        },
        "from_number": call.from_number,
        "to_number": call.to_number,
        "channel": call.channel,
        "origin": call.origin,
        "disconnect_reason": call.disconnect_reason,
        "duration_s": int(call.billable_seconds or 0),
        "status": call.status,
        "connected_at": call.connected_at.isoformat() if call.connected_at else None,
        "cost_usd": float(call.cost_total_usd) if call.cost_total_usd is not None else None,
        "latency_avg_ms": (call.latency_stats or {}).get("e2e_avg_ms"),
        "has_recording": call.recording_status == "available" and bool(call.recording_key),
        "summary": None if pending else call.summary,
        "sentiment": None if pending else call.sentiment,
        "analysis_values": None if pending else call.analysis,
        "analysis_status": None if pending else analysis_status(call, analysis),
        "quality": quality.as_json(),
    }


def analysis_status(call: Call, analysis: tuple[str, str | None] | None) -> str:
    """Why a row does or does not have a summary, for the list (007 analysis row, if any)."""
    if analysis is None:
        return "completed" if call.summary else "not_run"
    status, skip_reason = analysis
    if status in ("pending", "running"):
        return "running"
    if status == "skipped":
        return skip_reason or "not_run"
    return status


async def list_calls(
    session: AsyncSession, q: CallListQuery, *, page: int, page_size: int, user_id: str
) -> tuple[list[dict[str, Any]], int]:
    where = conditions(q, user_id)
    total = int(
        (await session.execute(select(func.count()).select_from(Call).where(and_(*where)))).scalar_one()
    )
    rows = (
        await session.execute(
            _base().where(and_(*where)).order_by(*_order(q)).slice(*page_window(page, page_size))
        )
    ).all()
    ids = [r[0].id for r in rows]
    summaries = await registry.quality.summaries(session, ids, user_id)
    states = await registry.quality.analysis_states(session, ids)
    items = [
        list_item(c, name, deleted, summaries.get(c.id, QualitySummary()), states.get(c.id))
        for c, name, deleted in rows
    ]
    return items, total


LIVE_LIMIT = 50
LAST_MESSAGE_CHARS = 200


async def live_calls(session: AsyncSession) -> tuple[list[dict[str, Any]], int]:
    """Calls on air now (queued, ringing, in progress), newest first, with the latest line heard.

    Two small indexed reads (``ix_calls_heartbeat`` leads with ``status``; events by the
    ``(call_id, seq)`` unique key), so clients can poll it every few seconds. Simulations are
    excluded: they are text runs, never on air. Calls a worker abandoned are swept out of these
    statuses by ``reap_stuck`` (jobs), so the list cannot fill with ghosts.
    """
    where = and_(Call.status.in_(tuple(ACTIVE_STATUSES)), Call.origin.in_(DEFAULT_ORIGINS))
    count = int((await session.execute(select(func.count()).select_from(Call).where(where))).scalar_one())
    rows = (
        await session.execute(
            _base().where(where).order_by(Call.created_at.desc(), Call.id.desc()).limit(LIVE_LIMIT)
        )
    ).all()
    ids = [r[0].id for r in rows if r[0].status == "in_progress"]
    last: dict[str, dict[str, str]] = {}
    if ids:
        events = await session.execute(
            text(
                "select distinct on (call_id) call_id, payload from call_events "
                "where call_id = any(:ids) and type = 'transcript_item' "
                "and payload->'item'->>'type' = 'message' "
                "and coalesce(payload->'item'->>'text', '') <> '' "
                "order by call_id, seq desc"
            ),
            {"ids": ids},
        )
        for e in events:
            item = (e.payload or {}).get("item") or {}
            text_ = " ".join(str(item.get("text") or "").split())
            if len(text_) > LAST_MESSAGE_CHARS:
                text_ = text_[: LAST_MESSAGE_CHARS - 1].rstrip() + "\u2026"
            last[e.call_id] = {"role": "user" if item.get("role") == "user" else "agent", "text": text_}
    items = [
        {
            "call_id": c.id,
            "status": c.status,
            "channel": c.channel,
            "direction": c.direction,
            "origin": c.origin,
            "agent": {"id": c.agent_id, "name": name or "Unknown agent", "deleted": deleted is not None},
            "from_number": c.from_number,
            "to_number": c.to_number,
            "started_at": c.created_at.isoformat(),
            "ringing_at": c.ringing_at.isoformat() if c.ringing_at else None,
            "connected_at": c.connected_at.isoformat() if c.connected_at else None,
            "last_message": last.get(c.id),
        }
        for c, name, deleted in rows
    ]
    return items, count


async def iter_export_rows(
    session: AsyncSession, q: CallListQuery, *, limit: int, user_id: str
) -> tuple[int, list[dict[str, Any]]]:
    where = conditions(q, user_id)
    total = int(
        (await session.execute(select(func.count()).select_from(Call).where(and_(*where)))).scalar_one()
    )
    if total > limit:
        return total, []
    rows = (await session.execute(_base().where(and_(*where)).order_by(*_order(q)))).all()
    summaries = await registry.quality.summaries(session, [r[0].id for r in rows], user_id)
    return total, [
        list_item(c, name, deleted, summaries.get(c.id, QualitySummary())) for c, name, deleted in rows
    ]


def latency_summary(stats: Mapping[str, Any] | None) -> dict[str, Any]:
    stats = stats or {}
    return {
        "avg_ms": stats.get("e2e_avg_ms"),
        "p50_ms": stats.get("e2e_p50_ms"),
        "p95_ms": stats.get("e2e_p95_ms"),
        "turns_measured": int(stats.get("turns") or 0),
    }


async def load_call(session: AsyncSession, call_id: str) -> tuple[Call, str | None, datetime | None] | None:
    row = (await session.execute(_base().where(Call.id == call_id))).first()
    return (row[0], row[1], row[2]) if row else None


async def call_detail(session: AsyncSession, call_id: str, user_id: str) -> dict[str, Any] | None:
    loaded = await load_call(session, call_id)
    if loaded is None:
        return None
    call, name, deleted = loaded
    quality = (await registry.quality.summaries(session, [call.id], user_id)).get(call.id, QualitySummary())
    snapshot = await snapshot_for(session, call.agent_version_id)
    version_number = snapshot.version_number if snapshot is not None else None
    detail = list_item(call, name, deleted, quality)
    detail.update(
        {
            "agent_version_id": call.agent_version_id or "",
            "agent_version_label": f"v{version_number}" if version_number else None,
            "ended_at": call.ended_at.isoformat() if call.ended_at else None,
            "latency": latency_summary(call.latency_stats),
            "cost": cost_view(call.cost_breakdown),
            "processing_state": "pending" if call.status in PENDING_STATES else "done",
            # The recorder finishes its upload a few seconds after the call ends; clients keep
            # polling while this is true instead of showing "no recording".
            "recording_pending": call.recording_status == "recording",
        }
    )
    return detail


async def _events(session: AsyncSession, call_id: str, types: Sequence[str]) -> list[CallEvent]:
    return list(
        (
            await session.execute(
                select(CallEvent)
                .where(CallEvent.call_id == call_id, CallEvent.type.in_(types))
                .order_by(CallEvent.seq)
            )
        ).scalars()
    )


async def transcript_items(session: AsyncSession, call: Call) -> list[dict[str, Any]]:
    """The finalised transcript, or the items received so far while the call is live."""
    if call.transcript is not None:
        raw = stored_items(call.transcript)
    else:
        raw = [
            dict(e.payload.get("item") or {}) for e in await _events(session, call.id, ("transcript_item",))
        ]
    return normalize_items(raw)


async def turn_latencies(session: AsyncSession, call_id: str) -> list[dict[str, Any]]:
    turns: dict[int, dict[str, Any]] = {}
    for e in await _events(session, call_id, ("turn",)):
        index = int(e.turn_index or 0)
        turns[index] = {
            "turn_index": index,
            "stt_final_ms": e.stt_final_ms,
            "llm_ttft_ms": e.llm_ttft_ms,
            "tts_ttfb_ms": e.tts_ttfb_ms,
            "e2e_ms": e.e2e_ms,
        }
    return [turns[k] for k in sorted(turns)]


async def flow_path(session: AsyncSession, call_id: str) -> list[dict[str, Any]]:
    """Flow transitions in order from ``flow_transition`` events (the compare page's flow diff)."""
    out: list[dict[str, Any]] = []
    for e in await _events(session, call_id, ("flow_transition",)):
        p = e.payload or {}
        out.append(
            {
                "sequence": len(out) + 1,
                "from_node_id": p.get("from_node_id"),
                "to_node_id": p.get("to_node_id"),
                "label": p.get("label"),
            }
        )
    return out


__all__ = [
    "CallListQuery",
    "call_detail",
    "conditions",
    "date_window",
    "digits",
    "flow_path",
    "iter_export_rows",
    "latency_summary",
    "list_calls",
    "load_call",
    "parse_list_query",
    "split_csv",
    "transcript_items",
    "turn_latencies",
]
