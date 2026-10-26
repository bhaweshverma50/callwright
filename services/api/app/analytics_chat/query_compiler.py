"""MetricQuery to SQLAlchemy Core over the ``analytics`` views (006 T064, research R4).

The compiler is the only path from the model to the database: relations are the three
``analytics.*`` views, columns come from fixed tables below, and every value (dates, timezone,
filter values, limit) is a bound parameter. The query fetches ``limit + 1`` rows so the caller can
tell when a result was cut.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import (
    Date,
    Float,
    Integer,
    Select,
    and_,
    bindparam,
    case,
    cast,
    column,
    func,
    literal_column,
    select,
    table,
)
from sqlalchemy.sql.elements import ColumnElement

from app.analytics_chat.catalog import Source
from app.analytics_chat.schemas import MetricQuery, Period

calls_v = table(
    "calls_v",
    column("call_id"),
    column("agent_id"),
    column("agent_name"),
    column("channel"),
    column("status"),
    column("disconnect_reason"),
    column("sentiment"),
    column("started_at"),
    column("duration_s"),
    column("cost_usd"),
    schema="analytics",
)
latency_v = table(
    "turn_latency_v",
    column("call_id"),
    column("agent_id"),
    column("occurred_at"),
    column("e2e_ms"),
    schema="analytics",
)
verdicts_v = table(
    "evaluator_verdicts_v",
    column("call_id"),
    column("agent_id"),
    column("evaluator_name"),
    column("verdict"),
    column("score"),
    column("started_at"),
    schema="analytics",
)


def _day_start(d: date, zone: ZoneInfo) -> datetime:
    return datetime(d.year, d.month, d.day, tzinfo=zone).astimezone(UTC)


def resolve_period(period: Period, tz: str, today: date) -> tuple[datetime, datetime]:
    """Calendar periods in ``tz`` as ``[start, end)`` in UTC. Weeks start on Monday."""
    zone = ZoneInfo(tz)
    first: date
    last: date  # inclusive
    if period.preset == "today":
        first = last = today
    elif period.preset == "yesterday":
        first = last = today - timedelta(days=1)
    elif period.preset == "this_week":
        first, last = today - timedelta(days=today.weekday()), today
    elif period.preset == "last_week":
        first = today - timedelta(days=today.weekday() + 7)
        last = first + timedelta(days=6)
    elif period.preset == "this_month":
        first, last = today.replace(day=1), today
    elif period.preset == "last_month":
        last = today.replace(day=1) - timedelta(days=1)
        first = last.replace(day=1)
    elif period.preset == "last_n_days":
        first, last = today - timedelta(days=(period.n_days or 1) - 1), today
    else:
        assert period.start_date is not None and period.end_date is not None
        first, last = period.start_date, period.end_date
    return _day_start(first, zone), _day_start(last + timedelta(days=1), zone)


def _source(source: Source) -> tuple[Any, ColumnElement[Any]]:
    if source == "calls":
        return calls_v, calls_v.c.started_at
    if source == "latency":
        return latency_v, latency_v.c.occurred_at
    return verdicts_v, verdicts_v.c.started_at


def _metric(name: str) -> ColumnElement[Any]:
    c, lat, v = calls_v.c, latency_v.c, verdicts_v.c
    decided = func.count().filter(v.verdict.in_([bindparam("v_pass", "pass"), bindparam("v_fail", "fail")]))
    expressions: dict[str, ColumnElement[Any]] = {
        "call_count": func.count(),
        "total_duration_s": func.coalesce(func.sum(c.duration_s), 0),
        "avg_duration_s": func.round(cast(func.avg(case((c.duration_s > 0, c.duration_s))), Float), 1),
        "total_cost_usd": func.coalesce(func.sum(c.cost_usd), 0),
        "avg_cost_usd": func.avg(c.cost_usd),
        "positive_sentiment_share": func.avg(
            case((c.sentiment == bindparam("s_pos", "positive"), 1.0), else_=0.0)
        ),
        "negative_sentiment_share": func.avg(
            case((c.sentiment == bindparam("s_neg", "negative"), 1.0), else_=0.0)
        ),
        "median_turn_latency_ms": func.percentile_cont(0.5).within_group(lat.e2e_ms.asc()),
        "p95_turn_latency_ms": func.percentile_cont(0.95).within_group(lat.e2e_ms.asc()),
        "evaluator_pass_rate": cast(func.count().filter(v.verdict == bindparam("v_pass2", "pass")), Float)
        / func.nullif(decided, 0),
        "evaluator_run_count": func.count(),
    }
    return expressions[name]


def _dimension(name: str, view: Any, when: ColumnElement[Any], tz: Any) -> list[ColumnElement[Any]]:
    local = func.timezone(tz, when)
    if name in ("day", "week", "month"):
        return [cast(func.date_trunc(name, local), Date).label(name)]
    if name == "hour_of_day":
        return [cast(func.date_part(bindparam("p_hour", "hour"), local), Integer).label(name)]
    if name == "weekday":
        return [cast(func.date_part(bindparam("p_isodow", "isodow"), local), Integer).label(name)]
    if name == "agent":
        if view is calls_v:
            return [view.c.agent_id.label("agent_id"), func.max(view.c.agent_name).label("agent_name")]
        return [view.c.agent_id.label("agent_id")]
    if name == "evaluator":
        return [view.c.evaluator_name.label("evaluator")]
    return [view.c[name].label(name)]


def compile_query(query: MetricQuery, *, tz: str, today: date) -> Select[Any]:
    view, when = _source(query.source)
    start, end = resolve_period(query.period, tz, today)
    tz_param: Any = bindparam("tz", tz)
    where: list[ColumnElement[bool]] = [when >= bindparam("start", start), when < bindparam("end", end)]
    f = query.filters
    for values, col, key in (
        (f.agent_ids, "agent_id", "agent_ids"),
        (f.channels, "channel", "channels"),
        (f.statuses, "status", "statuses"),
        (f.disconnect_reasons, "disconnect_reason", "disconnect_reasons"),
        (f.evaluator_names, "evaluator_name", "evaluator_names"),
    ):
        if values:
            where.append(view.c[col].in_(bindparam(key, list(values), expanding=True)))
    if f.sentiments:
        where.append(
            func.coalesce(view.c.sentiment, "unknown").in_(
                bindparam("sentiments", list(f.sentiments), expanding=True)
            )
        )

    group_cols: list[ColumnElement[Any]] = []
    for d in query.group_by:
        group_cols.extend(_dimension(d, view, when, tz_param))
    # Group by output position so the grouped expressions (with their bound timezone) are written once.
    keys: list[Any] = [literal_column(str(i + 1)) for i, c in enumerate(group_cols) if c.name != "agent_name"]
    metric_cols = [_metric(m).label(m) for m in query.metrics]
    stmt = select(*group_cols, *metric_cols).select_from(view).where(and_(*where))
    if keys:
        stmt = stmt.group_by(*keys)
    if query.order_by:
        key = "agent_name" if query.order_by.key == "agent" and view is calls_v else query.order_by.key
        key = "agent_id" if key == "agent" else key
        ordered: Any = column(key)
        stmt = stmt.order_by(
            ordered.asc() if query.order_by.direction == "asc" else ordered.desc().nulls_last()
        )
    elif any(d in ("day", "week", "month", "hour_of_day", "weekday") for d in query.group_by):
        stmt = stmt.order_by(*[column(d).asc() for d in query.group_by])
    elif query.group_by:
        stmt = stmt.order_by(column(query.metrics[0]).desc().nulls_last())
    return stmt.limit(bindparam("row_limit", query.limit + 1))
