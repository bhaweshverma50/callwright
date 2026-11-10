"""Pure scoring rules (007 T007; FR-015, FR-016; data-model "Derived values").

* ``run_verdict``: a run's overall verdict and score from its items.
"""

from __future__ import annotations

import statistics
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal, get_args

from app.evaluators.base import Verdict

RunStatus = Literal["pending", "running", "completed", "skipped", "error"]
EvalStatus = Literal["not_evaluated", "running", "passed", "failed", "error"]
EVAL_STATUSES: tuple[str, ...] = get_args(EvalStatus)


@dataclass(frozen=True)
class ItemOutcome:
    verdict: Verdict
    score: float | None = None


@dataclass(frozen=True)
class RunState:
    status: RunStatus
    verdict: Verdict | None = None


def run_verdict(items: Sequence[ItemOutcome], *, max_failed_items: int = 0) -> tuple[Verdict, float | None]:
    """Fail when failing items exceed ``max_failed_items``; pass when any item applies otherwise;
    not applicable when none applies. The score is the mean of applicable items' scores."""
    applicable = [i for i in items if i.verdict != "not_applicable"]
    if not applicable:
        return "not_applicable", None
    failed = sum(1 for i in applicable if i.verdict == "fail")
    verdict: Verdict = "fail" if failed > max_failed_items else "pass"
    scores = [i.score for i in applicable if i.score is not None]
    return verdict, (statistics.fmean(scores) if scores else None)


def run_counts(runs: Sequence[RunState]) -> tuple[int, int]:
    """(pass_count, fail_count) over completed runs."""
    passes = sum(1 for r in runs if r.status == "completed" and r.verdict == "pass")
    fails = sum(1 for r in runs if r.status == "completed" and r.verdict == "fail")
    return passes, fails
