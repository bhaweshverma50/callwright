"""Metric and dimension catalog for the analytics assistant (006 T062, research R4).

Every metric reads one source view in the ``analytics`` schema; a query's metrics share a source
and its dimensions must exist on that source.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Source = Literal["calls", "latency", "verdicts"]
Unit = Literal["count", "seconds", "usd", "ms", "ratio"]


@dataclass(frozen=True)
class Metric:
    name: str
    label: str
    unit: Unit
    source: Source


METRICS: dict[str, Metric] = {
    m.name: m
    for m in (
        Metric("call_count", "Calls", "count", "calls"),
        Metric("total_duration_s", "Talk time", "seconds", "calls"),
        Metric("avg_duration_s", "Average duration", "seconds", "calls"),
        Metric("total_cost_usd", "Total cost", "usd", "calls"),
        Metric("avg_cost_usd", "Average cost", "usd", "calls"),
        Metric("positive_sentiment_share", "Positive share", "ratio", "calls"),
        Metric("negative_sentiment_share", "Negative share", "ratio", "calls"),
        Metric("median_turn_latency_ms", "Median turn latency", "ms", "latency"),
        Metric("p95_turn_latency_ms", "p95 turn latency", "ms", "latency"),
        Metric("evaluator_pass_rate", "Pass rate", "ratio", "verdicts"),
        Metric("evaluator_run_count", "Evaluator runs", "count", "verdicts"),
    )
}

TIME_DIMENSIONS = ("day", "week", "month", "hour_of_day", "weekday")
DIMENSION_LABELS = {
    "day": "Day",
    "week": "Week",
    "month": "Month",
    "hour_of_day": "Hour of day",
    "weekday": "Weekday",
    "agent": "Agent",
    "channel": "Channel",
    "status": "Status",
    "disconnect_reason": "Ended by",
    "sentiment": "Sentiment",
    "evaluator": "Evaluator",
}
# Dimensions each source can group by.
SOURCE_DIMENSIONS: dict[Source, frozenset[str]] = {
    "calls": frozenset({*TIME_DIMENSIONS, "agent", "channel", "status", "disconnect_reason", "sentiment"}),
    "latency": frozenset({*TIME_DIMENSIONS, "agent"}),
    "verdicts": frozenset({*TIME_DIMENSIONS, "agent", "evaluator"}),
}
SOURCE_FILTERS: dict[Source, frozenset[str]] = {
    "calls": frozenset({"agent_ids", "channels", "statuses", "disconnect_reasons", "sentiments"}),
    "latency": frozenset({"agent_ids"}),
    "verdicts": frozenset({"agent_ids", "evaluator_names"}),
}
PERIODS = (
    "today",
    "yesterday",
    "this_week",
    "last_week",
    "this_month",
    "last_month",
    "last_n_days",
    "between",
)

SUGGESTED_QUESTIONS = (
    "How many calls did each agent take last week?",
    "Cost by agent this month",
    "Busiest day last week",
    "Average call duration trend over the last 30 days",
    "Median turn latency by agent this month",
    "Why did calls end yesterday?",
)


def catalog_json() -> dict[str, object]:
    return {
        "metrics": [{"name": m.name, "label": m.label, "unit": m.unit} for m in METRICS.values()],
        "group_by": list(DIMENSION_LABELS),
        "filters": sorted(set().union(*SOURCE_FILTERS.values())),
        "periods": list(PERIODS),
        "suggested_questions": list(SUGGESTED_QUESTIONS),
    }
