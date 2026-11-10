"""Dashboard aggregates (006 T044, T045; FR-018 to FR-022, research R1, R2).

Aggregate SQL over 003's ``calls`` (and ``call_events`` for turn latency) inside the RLS
transaction; no rollup tables. Counted calls are origin ``live`` and no longer active (queued,
ringing and in-progress calls join the totals once they end). Duration and cost come only from
``ended``, ``processing`` and ``completed`` calls, and cost is the sum of the priced call totals,
so it equals the itemised costs. Day buckets are calendar days in the viewer's timezone.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from typing import Any

from callwright_contract.calls import ACTIVE_STATUSES, CHANNELS
from sqlalchemy import Date, and_, case, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.agents.models import Agent
from app.calls.models import Call, CallEvent
from app.calls.ports import registry
from app.calls.quality_port import EvaluatorStat
from app.core.money import SIX
from app.dashboard.aggregates import daily_average, delta_pp, top_with_others, zero_fill
from app.dashboard.periods import Window

FINISHED = ("ended", "processing", "completed")
SENTIMENTS = ("positive", "neutral", "negative", "unknown")


def _where(window: Window, agent_ids: Sequence[str]) -> list[ColumnElement[bool]]:
    where: list[ColumnElement[bool]] = [
        Call.origin == "live",
        Call.status.not_in(tuple(ACTIVE_STATUSES)),
        Call.created_at >= window.start,
        Call.created_at < window.end,
    ]
    if agent_ids:
        where.append(Call.agent_id.in_(agent_ids))
    return where


def _money(value: Any) -> float:
    return float(Decimal(value or 0).quantize(SIX))


async def first_call_day(session: AsyncSession, tz: str, agent_ids: Sequence[str]) -> date | None:
    where: list[ColumnElement[bool]] = [Call.origin == "live"]
    if agent_ids:
        where.append(Call.agent_id.in_(agent_ids))
    value = (
        await session.execute(
            select(cast(func.timezone(tz, func.min(Call.created_at)), Date)).where(and_(*where))
        )
    ).scalar_one_or_none()
    return value if isinstance(value, date) else None


async def stats(session: AsyncSession, window: Window, agent_ids: Sequence[str]) -> dict[str, Any]:
    tz = window.tz.key
    where = and_(*_where(window, agent_ids))
    local = func.timezone(tz, Call.created_at)
    finished = Call.status.in_(FINISHED)
    duration = case((finished, func.coalesce(Call.billable_seconds, 0)), else_=None)
    talked = case(
        (and_(finished, func.coalesce(Call.billable_seconds, 0) > 0), Call.billable_seconds), else_=None
    )
    cost = case((finished, Call.cost_total_usd), else_=None)
    bucket = cast(func.date_trunc(window.bucket, local), Date)

    series_rows = (
        await session.execute(
            select(
                bucket.label("b"),
                func.count().label("calls"),
                func.coalesce(func.sum(duration), 0).label("dur"),
                func.coalesce(func.sum(cost), 0).label("cost"),
                func.avg(talked).label("avg_dur"),
            )
            .where(where)
            .group_by(bucket)
        )
    ).all()
    by_bucket = {
        r.b: {
            "total_calls": int(r.calls),
            "total_duration_s": int(r.dur),
            "avg_duration_s": round(float(r.avg_dur or 0), 1),
            "_cost": _money(r.cost),
        }
        for r in series_rows
    }
    filled = zero_fill(
        by_bucket,
        window.start_date,
        window.end_date,
        window.bucket,
        {"total_calls": 0, "total_duration_s": 0, "avg_duration_s": 0.0, "_cost": 0.0},
    )
    sparkline_cost = [s.pop("_cost") for s in filled]

    totals = (
        await session.execute(
            select(
                func.count().label("calls"),
                func.coalesce(func.sum(duration), 0).label("dur"),
                func.coalesce(func.sum(cost), 0).label("cost"),
                func.avg(talked).label("avg_dur"),
            ).where(where)
        )
    ).one()
    day = cast(local, Date)
    peak = (
        await session.execute(
            select(day.label("d"), func.count().label("n"))
            .where(where)
            .group_by(day)
            .order_by(func.count().desc(), day)
            .limit(1)
        )
    ).first()

    reasons = {
        str(r[0]): int(r[1])
        for r in (
            await session.execute(
                select(Call.disconnect_reason, func.count())
                .where(where, Call.disconnect_reason.is_not(None))
                .group_by(Call.disconnect_reason)
            )
        ).all()
    }
    sentiment_col = func.coalesce(Call.sentiment, "unknown")
    sentiment = dict.fromkeys(SENTIMENTS, 0)
    for value, n in (
        await session.execute(select(sentiment_col, func.count()).where(where).group_by(sentiment_col))
    ).all():
        key = value if value in sentiment else "unknown"
        sentiment[key] += int(n)
    channels = dict.fromkeys(CHANNELS, 0)
    for value, n in (
        await session.execute(select(Call.channel, func.count()).where(where).group_by(Call.channel))
    ).all():
        if value in channels:
            channels[value] = int(n)

    agent_rows = (
        await session.execute(
            select(
                Call.agent_id,
                func.max(Agent.name),
                func.count(),
                func.count().filter(Call.sentiment == "positive"),
                func.count().filter(Call.sentiment == "negative"),
            )
            .outerjoin(Agent, Agent.id == Call.agent_id)
            .where(where)
            .group_by(Call.agent_id)
        )
    ).all()
    agents = [
        (str(a), str(name or "Unknown agent"), int(n), int(pos), int(neg))
        for a, name, n, pos, neg in agent_rows
    ]
    leaderboard = [
        {"agent_id": a, "agent_name": name, "total_calls": n, "positive_calls": pos, "negative_calls": neg}
        for a, name, n, pos, neg in sorted(agents, key=lambda r: (-r[2], r[1]))[:5]
    ]

    turn_where = [
        CallEvent.type == "turn",
        CallEvent.turn_index > 0,
        CallEvent.e2e_ms.is_not(None),
    ]
    latency = (
        await session.execute(
            select(
                func.percentile_cont(0.5).within_group(CallEvent.e2e_ms.asc()),
                func.percentile_cont(0.95).within_group(CallEvent.e2e_ms.asc()),
            )
            .select_from(CallEvent)
            .join(Call, Call.id == CallEvent.call_id)
            .where(where, *turn_where)
        )
    ).one()

    total_calls = int(totals.calls)
    total_cost = _money(totals.cost)
    return {
        "window": window.as_json(),
        "bucket": window.bucket,
        "kpis": {
            "total_calls": total_calls,
            "daily_avg_calls": daily_average(total_calls, window.days),
            "total_duration_s": int(totals.dur),
            "peak_day": {"date": peak.d.isoformat(), "total_calls": int(peak.n)} if peak else None,
            "total_cost_usd": total_cost,
            "cost_per_call_usd": round(total_cost / total_calls, 6) if total_calls else 0,
            "avg_duration_s": round(float(totals.avg_dur or 0), 1),
            "median_turn_latency_ms": None if latency[0] is None else round(latency[0]),
            "p95_turn_latency_ms": None if latency[1] is None else round(latency[1]),
        },
        "sparklines": {
            "calls": [s["total_calls"] for s in filled],
            "duration_s": [s["total_duration_s"] for s in filled],
            "cost_usd": sparkline_cost,
            "avg_duration_s": [s["avg_duration_s"] for s in filled],
        },
        "series": filled,
        "disconnect_reasons": reasons,
        "sentiment": sentiment,
        "channels": channels,
        "leaderboard": leaderboard,
        "distribution": top_with_others([(a, name, n) for a, name, n, _, _ in agents], 10),
    }


def _stat_json(s: EvaluatorStat) -> dict[str, Any]:
    return {
        "evaluator_id": s.evaluator_id,
        "evaluator_name": s.evaluator_name,
        "display_name": s.display_name,
        "scope": s.scope,
        "pass_rate": s.pass_rate,
        "avg_score": s.avg_score,
        "pass_count": s.pass_count,
        "fail_count": s.fail_count,
        "not_applicable_count": s.not_applicable_count,
        "total_runs": s.total_runs,
        "calls_evaluated": s.calls_evaluated,
    }


async def quality(
    session: AsyncSession, window: Window, agent_ids: Sequence[str], compare: bool
) -> dict[str, Any]:
    port = registry.quality
    current, evaluated = await port.window_stats(
        session, start=window.start, end=window.end, agent_ids=agent_ids
    )
    body: dict[str, Any] = {
        "window": window.as_json(),
        "prior_window": None,
        "total_calls_evaluated": evaluated,
        "per_evaluator": [_stat_json(s) for s in current],
        "per_evaluator_prior": [],
    }
    if compare:
        prior = window.prior()
        before, _ = await port.window_stats(session, start=prior.start, end=prior.end, agent_ids=agent_ids)
        body["prior_window"] = prior.as_json()
        body["per_evaluator_prior"] = [_stat_json(s) for s in before]
    return body


async def agent_health(session: AsyncSession, window: Window, agent_ids: Sequence[str]) -> dict[str, Any]:
    """Headline evaluators: last 30 days against the 30 before, at most 4, by run count."""
    port = registry.quality
    prior = window.prior()
    current, _ = await port.window_stats(session, start=window.start, end=window.end, agent_ids=agent_ids)
    before, _ = await port.window_stats(session, start=prior.start, end=prior.end, agent_ids=agent_ids)
    prior_by_id = {s.evaluator_id: s for s in before}
    headline = sorted((s for s in current if s.headline), key=lambda s: -s.total_runs)[:4]
    items = []
    for s in headline:
        old = prior_by_id.get(s.evaluator_id)
        prior_rate = old.pass_rate if old else None
        items.append(
            {
                "evaluator_id": s.evaluator_id,
                "display_name": s.display_name,
                "pass_rate": s.pass_rate,
                "prior_pass_rate": prior_rate,
                "delta_pp": delta_pp(s.pass_rate, prior_rate),
            }
        )
    return {"window": window.as_json(), "prior_window": prior.as_json(), "items": items}
