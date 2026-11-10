"""Analytics assistant request and query schemas (006 T063, contracts/analytics_chat.yaml).

``MetricQuery`` (aggregates over a period) and ``CallQuery`` (specific or recent calls) are the
only things the model can ask for. Unknown names, extra keys, oversized
lists and mixed sources fail validation; agent IDs are checked against the workspace separately
(``check_agents``) because that needs the database.
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from callwright_contract.calls import CallStatus, Channel, DisconnectReason
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.analytics_chat.catalog import METRICS, SOURCE_DIMENSIONS, SOURCE_FILTERS, Source
from app.calls.origins import Origin

MetricName = Literal[
    "call_count",
    "total_duration_s",
    "avg_duration_s",
    "total_cost_usd",
    "avg_cost_usd",
    "median_turn_latency_ms",
    "p95_turn_latency_ms",
    "evaluator_pass_rate",
    "evaluator_run_count",
    "positive_sentiment_share",
    "negative_sentiment_share",
]
Dimension = Literal[
    "day",
    "week",
    "month",
    "hour_of_day",
    "weekday",
    "agent",
    "channel",
    "status",
    "disconnect_reason",
    "sentiment",
    "evaluator",
]
SentimentName = Literal["positive", "neutral", "negative", "unknown"]


class QueryRejected(ValueError):
    """A query that validates structurally but may not run (another workspace's agent)."""


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Filters(_Strict):
    agent_ids: list[str] = Field(default_factory=list, max_length=50)
    channels: list[Channel] = Field(default_factory=list, max_length=4)
    statuses: list[CallStatus] = Field(default_factory=list, max_length=10)
    disconnect_reasons: list[DisconnectReason] = Field(default_factory=list, max_length=9)
    sentiments: list[SentimentName] = Field(default_factory=list, max_length=4)
    evaluator_names: list[str] = Field(default_factory=list, max_length=20)

    def used(self) -> set[str]:
        return {k for k, v in self.model_dump().items() if v}


class Period(_Strict):
    preset: Literal[
        "today", "yesterday", "this_week", "last_week", "this_month", "last_month", "last_n_days", "between"
    ]
    n_days: int | None = Field(default=None, ge=1, le=365)
    start_date: date | None = None
    end_date: date | None = None

    @model_validator(mode="after")
    def _complete(self) -> Period:
        if self.preset == "last_n_days" and self.n_days is None:
            raise ValueError("last_n_days needs n_days")
        if self.preset == "between":
            if self.start_date is None or self.end_date is None:
                raise ValueError("between needs start_date and end_date")
            if self.end_date < self.start_date or (self.end_date - self.start_date).days > 730:
                raise ValueError("between needs an end on or after the start, at most 731 days")
        return self


class OrderBy(_Strict):
    key: str
    direction: Literal["asc", "desc"] = "desc"


def _live() -> list[Origin]:
    return ["live"]


def _live_and_test() -> list[Origin]:
    return ["live", "test"]


def _unique_origins(origins: list[Origin]) -> None:
    if len(set(origins)) != len(origins):
        raise ValueError("origins repeats a value")


class MetricQuery(_Strict):
    kind: Literal["metrics"] = "metrics"
    metrics: list[MetricName] = Field(min_length=1, max_length=4)
    group_by: list[Dimension] = Field(default_factory=list, max_length=2)
    filters: Filters = Field(default_factory=Filters)
    period: Period
    order_by: OrderBy | None = None
    limit: int = Field(default=50, ge=1, le=100)
    # Aggregates count live calls unless the user asks to include test or simulated calls.
    origins: list[Origin] = Field(default_factory=_live, min_length=1, max_length=3)

    @property
    def source(self) -> Source:
        return METRICS[self.metrics[0]].source

    @model_validator(mode="after")
    def _coherent(self) -> MetricQuery:
        sources = {METRICS[m].source for m in self.metrics}
        if len(sources) > 1:
            raise ValueError(
                "metrics in one query must come from the same source; split them into separate queries"
            )
        source = self.source
        if not set(self.group_by) <= SOURCE_DIMENSIONS[source]:
            raise ValueError(f"group_by not available for {source} metrics")
        if len(set(self.group_by)) != len(self.group_by):
            raise ValueError("group_by repeats a dimension")
        if not self.filters.used() <= SOURCE_FILTERS[source]:
            raise ValueError(f"filters not available for {source} metrics")
        if self.order_by and self.order_by.key not in {*self.metrics, *self.group_by}:
            raise ValueError("order_by must name a metric or dimension of the query")
        if any(not a.startswith("agt_") for a in self.filters.agent_ids):
            raise ValueError("agent_ids must be agt_ IDs")
        _unique_origins(self.origins)
        return self


class CallFilters(_Strict):
    agent_ids: list[str] = Field(default_factory=list, max_length=50)
    channels: list[Channel] = Field(default_factory=list, max_length=4)
    statuses: list[CallStatus] = Field(default_factory=list, max_length=10)


class CallQuery(_Strict):
    """Specific or recent calls: the last call, the last N, the most expensive, one by ID.

    Includes test calls by default so "my last call" finds the call the owner just tested.
    """

    kind: Literal["calls"]
    call_id: str | None = Field(default=None, pattern=r"^call_[0-9A-HJKMNP-TV-Z]{26}$")
    order: Literal["recent", "cost", "duration", "latency"] = "recent"
    direction: Literal["asc", "desc"] = "desc"
    period: Period | None = None
    filters: CallFilters = Field(default_factory=CallFilters)
    origins: list[Origin] = Field(default_factory=_live_and_test, min_length=1, max_length=3)
    limit: int = Field(default=5, ge=1, le=20)

    @model_validator(mode="after")
    def _coherent(self) -> CallQuery:
        if any(not a.startswith("agt_") for a in self.filters.agent_ids):
            raise ValueError("agent_ids must be agt_ IDs")
        _unique_origins(self.origins)
        return self


AnyQuery = MetricQuery | CallQuery


def parse_query(data: object) -> AnyQuery:
    """Validate one planner query; ``kind: "calls"`` is a lookup, anything else a metric query."""
    if isinstance(data, dict) and data.get("kind") == "calls":
        return CallQuery.model_validate(data)
    return MetricQuery.model_validate(data)


def check_agents(query: AnyQuery, workspace_agents: set[str]) -> None:
    foreign = set(query.filters.agent_ids) - workspace_agents
    if foreign:
        raise QueryRejected("agent IDs outside this workspace")


class ChatMessageIn(_Strict):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=2000)


class ChatRequest(_Strict):
    messages: list[ChatMessageIn] = Field(min_length=1, max_length=20)
    timezone: str = Field(default="UTC", max_length=64)

    @model_validator(mode="after")
    def _last_is_user(self) -> ChatRequest:
        if self.messages[-1].role != "user":
            raise ValueError("the last message must be from the user")
        return self
