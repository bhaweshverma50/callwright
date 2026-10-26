"""MetricQuery validation (006 T058, FR-024): only catalog names, bounded sizes, own agents."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from app.analytics_chat.schemas import MetricQuery, QueryRejected, check_agents


def q(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {"metrics": ["call_count"], "period": {"preset": "last_n_days", "n_days": 7}}
    body.update(overrides)
    return body


def test_valid_query() -> None:
    m = MetricQuery.model_validate(q(group_by=["agent"], filters={"channels": ["whatsapp"]}, limit=10))
    assert m.metrics == ["call_count"] and m.limit == 10


@pytest.mark.parametrize(
    "bad",
    [
        q(metrics=["revenue"]),
        q(metrics=["call_count", "total_cost_usd", "avg_cost_usd", "total_duration_s", "avg_duration_s"]),
        q(group_by=["day", "agent", "channel"]),
        q(group_by=["customer"]),
        q(limit=101),
        q(limit=0),
        q(filters={"channels": ["fax"]}),
        q(filters={"sql": "1=1"}),
        q(period={"preset": "forever"}),
        q(period={"preset": "last_n_days", "n_days": 400}),
        q(period={"preset": "between", "start_date": "2026-10-10"}),
        q(raw_sql="select 1"),
        q(metrics=[]),
    ],
)
def test_rejected(bad: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        MetricQuery.model_validate(bad)


def test_mixed_sources_rejected() -> None:
    with pytest.raises(ValidationError):
        MetricQuery.model_validate(q(metrics=["call_count", "median_turn_latency_ms"]))


def test_dimension_must_fit_metric_source() -> None:
    with pytest.raises(ValidationError):
        MetricQuery.model_validate(q(metrics=["median_turn_latency_ms"], group_by=["channel"]))


def test_order_by_must_be_in_query() -> None:
    with pytest.raises(ValidationError):
        MetricQuery.model_validate(q(order_by={"key": "total_cost_usd", "direction": "desc"}))
    MetricQuery.model_validate(q(group_by=["agent"], order_by={"key": "agent", "direction": "asc"}))


def test_foreign_agent_rejected() -> None:
    m = MetricQuery.model_validate(q(filters={"agent_ids": ["agt_mine", "agt_theirs"]}))
    with pytest.raises(QueryRejected):
        check_agents(m, {"agt_mine"})
    check_agents(MetricQuery.model_validate(q(filters={"agent_ids": ["agt_mine"]})), {"agt_mine"})
