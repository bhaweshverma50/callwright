"""MetricQuery compiler (006 T059): catalog queries compile to SQL over analytics.* only, with every
value bound."""

from __future__ import annotations

import re
from datetime import UTC, date, datetime
from typing import Any

import pytest
from sqlalchemy.dialects import postgresql

from app.analytics_chat.query_compiler import compile_query, resolve_period
from app.analytics_chat.schemas import MetricQuery, Period

TODAY = date(2026, 10, 16)  # a Friday

QUERIES: list[dict[str, Any]] = [
    {"metrics": ["call_count"], "period": {"preset": "this_month"}},
    {"metrics": ["total_cost_usd"], "group_by": ["agent"], "period": {"preset": "this_month"}},
    {"metrics": ["call_count"], "group_by": ["day"], "period": {"preset": "last_week"}},
    {"metrics": ["avg_duration_s"], "group_by": ["week"], "period": {"preset": "last_n_days", "n_days": 90}},
    {"metrics": ["call_count", "total_duration_s"], "group_by": ["channel"], "period": {"preset": "today"}},
    {
        "metrics": ["median_turn_latency_ms", "p95_turn_latency_ms"],
        "group_by": ["agent"],
        "period": {"preset": "yesterday"},
    },
    {
        "metrics": ["call_count"],
        "group_by": ["disconnect_reason"],
        "filters": {"channels": ["whatsapp"], "statuses": ["completed"]},
        "period": {"preset": "last_month"},
    },
    {
        "metrics": ["positive_sentiment_share", "negative_sentiment_share"],
        "group_by": ["agent"],
        "period": {"preset": "this_week"},
    },
    {
        "metrics": ["evaluator_pass_rate", "evaluator_run_count"],
        "group_by": ["evaluator"],
        "period": {"preset": "last_n_days", "n_days": 30},
    },
    {
        "metrics": ["call_count"],
        "group_by": ["hour_of_day", "weekday"],
        "filters": {"agent_ids": ["agt_secretvalue01"]},
        "period": {"preset": "between", "start_date": "2026-09-01", "end_date": "2026-09-30"},
        "order_by": {"key": "call_count", "direction": "desc"},
        "limit": 5,
    },
]


def _sql(body: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    stmt = compile_query(MetricQuery.model_validate(body), tz="Asia/Kolkata", today=TODAY)
    compiled = stmt.compile(dialect=postgresql.dialect())
    return str(compiled), dict(compiled.params)


@pytest.mark.parametrize("body", QUERIES)
def test_only_analytics_relations(body: dict[str, Any]) -> None:
    sql, _ = _sql(body)
    relations = re.findall(r"\b(?:FROM|JOIN)\s+([a-z_\.]+)", sql)
    assert relations and all(r.startswith("analytics.") for r in relations), sql


@pytest.mark.parametrize("body", QUERIES)
def test_values_are_bound(body: dict[str, Any]) -> None:
    sql, params = _sql(body)
    for value in ("whatsapp", "completed", "agt_secretvalue01", "Asia/Kolkata"):
        assert value not in sql
    assert params, "every query binds at least the period"


def test_limit_fetches_one_more_to_detect_truncation() -> None:
    _, params = _sql(QUERIES[-1])
    assert 6 in params.values()


def test_group_columns_named_after_dimensions() -> None:
    sql, _ = _sql(QUERIES[1])
    assert "agent_name" in sql and "total_cost_usd" in sql


def test_periods() -> None:
    def window(**kw: Any) -> tuple[datetime, datetime]:
        return resolve_period(Period.model_validate(kw), "UTC", TODAY)

    assert window(preset="today") == (datetime(2026, 10, 16, tzinfo=UTC), datetime(2026, 10, 17, tzinfo=UTC))
    assert window(preset="yesterday")[0] == datetime(2026, 10, 15, tzinfo=UTC)
    assert window(preset="this_week")[0] == datetime(2026, 10, 12, tzinfo=UTC)
    assert window(preset="last_week") == (
        datetime(2026, 10, 5, tzinfo=UTC),
        datetime(2026, 10, 12, tzinfo=UTC),
    )
    assert window(preset="this_month")[0] == datetime(2026, 10, 1, tzinfo=UTC)
    assert window(preset="last_month") == (
        datetime(2026, 9, 1, tzinfo=UTC),
        datetime(2026, 10, 1, tzinfo=UTC),
    )
    assert window(preset="last_n_days", n_days=7) == (
        datetime(2026, 10, 10, tzinfo=UTC),
        datetime(2026, 10, 17, tzinfo=UTC),
    )
    kolkata = resolve_period(Period(preset="today"), "Asia/Kolkata", TODAY)
    assert kolkata[0] == datetime(2026, 10, 15, 18, 30, tzinfo=UTC)
