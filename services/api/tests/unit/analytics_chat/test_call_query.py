"""CallQuery (call lookups) and origins on MetricQuery: typed, bounded, read-only and compiled over
``analytics.*`` with every value bound. Live-only stays the default for aggregates; lookups include
test calls so "my last call" finds a test call."""

from __future__ import annotations

import re
from datetime import date
from typing import Any

import pytest
from pydantic import ValidationError
from sqlalchemy.dialects import postgresql

from app.analytics_chat.assistant import keyword_plan
from app.analytics_chat.query_compiler import compile_calls, compile_query
from app.analytics_chat.schemas import (
    CallQuery,
    ChatMessageIn,
    MetricQuery,
    QueryRejected,
    check_agents,
    parse_query,
)

TODAY = date(2026, 10, 16)
CALL_ID = "call_01JABCDEFGHJKMNPQRSTVWXYZ0"


def _sql(stmt: Any) -> tuple[str, dict[str, Any]]:
    compiled = stmt.compile(dialect=postgresql.dialect())
    return str(compiled), dict(compiled.params)


def test_call_query_defaults_include_test_calls() -> None:
    q = CallQuery.model_validate({"kind": "calls"})
    assert q.origins == ["live", "test"] and q.order == "recent" and q.limit == 5 and q.period is None


def test_metric_query_defaults_to_live_only() -> None:
    q = MetricQuery.model_validate({"metrics": ["call_count"], "period": {"preset": "today"}})
    assert q.origins == ["live"] and q.kind == "metrics"


@pytest.mark.parametrize(
    "bad",
    [
        {"kind": "calls", "limit": 0},
        {"kind": "calls", "limit": 21},
        {"kind": "calls", "order": "random"},
        {"kind": "calls", "origins": []},
        {"kind": "calls", "origins": ["prod"]},
        {"kind": "calls", "call_id": "1; drop table calls"},
        {"kind": "calls", "call_id": "agt_01JABCDEFGHJKMNPQRSTVWXYZ0"},
        {"kind": "calls", "filters": {"workspace_id": "ws_x"}},
        {"kind": "calls", "filters": {"agent_ids": ["not-an-agent"]}},
        {"kind": "calls", "raw_sql": "select 1"},
    ],
)
def test_invalid_call_queries_fail(bad: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        CallQuery.model_validate(bad)


def test_parse_query_dispatches_on_kind() -> None:
    assert isinstance(parse_query({"kind": "calls"}), CallQuery)
    assert isinstance(parse_query({"metrics": ["call_count"], "period": {"preset": "today"}}), MetricQuery)


def test_call_query_rejects_foreign_agents() -> None:
    q = CallQuery.model_validate({"kind": "calls", "filters": {"agent_ids": ["agt_theirs"]}})
    with pytest.raises(QueryRejected):
        check_agents(q, {"agt_mine"})


@pytest.mark.parametrize(
    "body",
    [
        {"kind": "calls"},
        {"kind": "calls", "order": "cost", "limit": 1, "period": {"preset": "this_month"}},
        {"kind": "calls", "call_id": CALL_ID},
        {
            "kind": "calls",
            "order": "latency",
            "filters": {"agent_ids": ["agt_secretvalue01"], "statuses": ["failed"]},
        },
        {"kind": "calls", "origins": ["simulation"], "order": "duration", "direction": "asc"},
    ],
)
def test_call_lookup_reads_analytics_only_and_binds_values(body: dict[str, Any]) -> None:
    sql, params = _sql(compile_calls(CallQuery.model_validate(body), tz="Asia/Kolkata", today=TODAY))
    relations = re.findall(r"\b(?:FROM|JOIN)\s+([a-z_\.]+)", sql)
    assert relations and all(r.startswith("analytics.") for r in relations), sql
    for value in (CALL_ID, "agt_secretvalue01", "failed", "simulation", "Asia/Kolkata", "test"):
        assert value not in sql
    assert params["origins"]
    assert "origin IN" in sql


def test_call_lookup_fetches_one_more_for_truncation() -> None:
    _, params = _sql(
        compile_calls(CallQuery.model_validate({"kind": "calls", "limit": 3}), tz="UTC", today=TODAY)
    )
    assert params["row_limit"] == 4


@pytest.mark.parametrize(
    ("body", "origins"),
    [
        ({"metrics": ["call_count"], "period": {"preset": "today"}}, ["live"]),
        ({"metrics": ["median_turn_latency_ms"], "period": {"preset": "today"}}, ["live"]),
        (
            {"metrics": ["total_cost_usd"], "period": {"preset": "today"}, "origins": ["live", "test"]},
            ["live", "test"],
        ),
    ],
)
def test_metric_queries_filter_on_origin(body: dict[str, Any], origins: list[str]) -> None:
    sql, params = _sql(compile_query(MetricQuery.model_validate(body), tz="UTC", today=TODAY))
    assert "origin IN" in sql and params["origins"] == origins


def _plan(question: str) -> dict[str, Any]:
    plan = keyword_plan([ChatMessageIn(role="user", content=question)])
    assert plan.decline is None and plan.queries, question
    return plan.queries[0]


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("what is cost for my last call", {"kind": "calls", "order": "recent", "limit": 1}),
        ("What did my latest call cost?", {"kind": "calls", "order": "recent", "limit": 1}),
        ("show my last 5 calls", {"kind": "calls", "order": "recent", "limit": 5}),
        ("which was the most expensive call this month", {"kind": "calls", "order": "cost", "limit": 1}),
        ("longest call last week", {"kind": "calls", "order": "duration", "limit": 1}),
        ("slowest call", {"kind": "calls", "order": "latency", "limit": 1}),
        ("list calls today", {"kind": "calls", "order": "recent", "period": {"preset": "today"}}),
        (f"how much did {CALL_ID.lower()} cost", {"kind": "calls", "call_id": CALL_ID}),
    ],
)
def test_keyword_planner_understands_call_lookups(question: str, expected: dict[str, Any]) -> None:
    query = _plan(question)
    for key, value in expected.items():
        assert query.get(key) == value, (question, query)
    CallQuery.model_validate(query)


def test_keyword_planner_origins() -> None:
    assert _plan("my last test call").get("origins") == ["test"]
    assert _plan("my last simulated call").get("origins") == ["simulation"]
    assert "origins" not in _plan("how many calls this week")
    assert _plan("how many calls this week, including test calls").get("origins") == ["live", "test"]
    assert _plan("how many calls today?").get("kind", "metrics") == "metrics"


def test_unanswerable_decline_offers_examples() -> None:
    plan = keyword_plan([ChatMessageIn(role="user", content="What is our churn rate?")])
    assert plan.decline and len(plan.suggestions) >= 2
