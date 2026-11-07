"""Quality data seam between 006 (reads) and 007 (owns verdicts and labels), research R3.

006 renders evaluation outcomes, the viewer's own labels and evaluator pass rates, but 007 owns
that data and depends on 006. 007 registers its implementation at start-up with
``ports.set_quality_port``; until then ``NullCallQualityPort`` answers with the empty states
("not evaluated", unannotated, no evaluator runs).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal, Protocol

from sqlalchemy import ColumnElement, false, true
from sqlalchemy.ext.asyncio import AsyncSession

EvalStatus = Literal["not_evaluated", "running", "passed", "failed", "error"]
Label = Literal["good", "bad"]
EVAL_STATUSES: tuple[EvalStatus, ...] = ("not_evaluated", "running", "passed", "failed", "error")
LABEL_FILTERS = ("good", "bad", "unannotated")


@dataclass(frozen=True)
class QualitySummary:
    eval_status: EvalStatus = "not_evaluated"
    pass_count: int = 0
    fail_count: int = 0
    label: Label | None = None

    def as_json(self) -> dict[str, object]:
        return {
            "eval_status": self.eval_status,
            "pass_count": self.pass_count,
            "fail_count": self.fail_count,
            "label": self.label,
        }


@dataclass(frozen=True)
class EvaluatorStat:
    evaluator_id: str
    evaluator_name: str
    display_name: str
    scope: Literal["call", "turn", "flow_node"]
    pass_count: int
    fail_count: int
    not_applicable_count: int
    total_runs: int
    calls_evaluated: int
    avg_score: float | None
    headline: bool = False

    @property
    def pass_rate(self) -> float | None:
        decided = self.pass_count + self.fail_count
        return None if decided == 0 else self.pass_count / decided


@dataclass(frozen=True)
class VerdictDiff:
    evaluator_id: str
    evaluator_name: str
    left_verdict: str | None
    left_score: float | None
    right_verdict: str | None
    right_score: float | None
    right_rationale: str | None


class CallQualityPort(Protocol):
    async def summaries(
        self, session: AsyncSession, call_ids: Sequence[str], user_id: str
    ) -> dict[str, QualitySummary]: ...

    def filter_clause(
        self,
        call_id_column: Any,
        *,
        labels: Sequence[str],
        eval_statuses: Sequence[str],
        user_id: str,
    ) -> ColumnElement[bool]: ...

    async def window_stats(
        self,
        session: AsyncSession,
        *,
        start: datetime,
        end: datetime,
        agent_ids: Sequence[str],
    ) -> tuple[list[EvaluatorStat], int]: ...

    async def verdict_diffs(
        self, session: AsyncSession, left_call_id: str, right_call_id: str
    ) -> list[VerdictDiff]: ...

    async def analysis_states(
        self, session: AsyncSession, call_ids: Sequence[str]
    ) -> dict[str, tuple[str, str | None]]:
        """``(status, skip_reason)`` of each call's post-call analysis, when one exists."""
        ...


class NullCallQualityPort:
    """No quality feature installed: every call is ``not_evaluated`` and unannotated."""

    async def summaries(
        self, session: AsyncSession, call_ids: Sequence[str], user_id: str
    ) -> dict[str, QualitySummary]:
        return {call_id: QualitySummary() for call_id in call_ids}

    def filter_clause(
        self,
        call_id_column: Any,
        *,
        labels: Sequence[str],
        eval_statuses: Sequence[str],
        user_id: str,
    ) -> ColumnElement[bool]:
        label_ok = not labels or "unannotated" in labels
        status_ok = not eval_statuses or "not_evaluated" in eval_statuses
        return true() if label_ok and status_ok else false()

    async def window_stats(
        self,
        session: AsyncSession,
        *,
        start: datetime,
        end: datetime,
        agent_ids: Sequence[str],
    ) -> tuple[list[EvaluatorStat], int]:
        return [], 0

    async def verdict_diffs(
        self, session: AsyncSession, left_call_id: str, right_call_id: str
    ) -> list[VerdictDiff]:
        return []

    async def analysis_states(
        self, session: AsyncSession, call_ids: Sequence[str]
    ) -> dict[str, tuple[str, str | None]]:
        return {}
