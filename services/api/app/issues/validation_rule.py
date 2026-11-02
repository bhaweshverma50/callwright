"""The keep rule (009 T037; spec FR-014, research R3). Pure, exact arithmetic.

Inputs are paired counts per evaluator and call set (``affected``, ``guard``, ``combined`` =
affected plus guard): ``n`` calls with a verdict in both arms at the same evaluator version, and
how many of them passed in the control and the treatment arm. Every comparison uses
``fractions.Fraction`` so the 10.0-point and 5.0-point boundaries are exact; display values are
rounded half away from zero only when reported.

Decision, in order:

1. ``inconclusive`` when the headline evaluator has fewer than ``min_sample`` pairs on the
   affected calls (``insufficient_sample``), or more than 20% of treatment runs failed
   (``too_many_failed_runs``).
2. ``failed`` when the headline's improvement on the affected calls is below
   ``min_improvement_pp`` (``improvement_below_threshold``), or when a regression check drops
   below ``-max_regression_pp`` (``regression``). Regression checks: every other evaluator on the
   combined set, and the headline on the guard set; a check with fewer than ``min_sample`` pairs
   does not count and is reported as ``insufficient_data``.
3. ``passed`` otherwise. Bounds are inclusive for passing: exactly +10 passes, exactly -5 does not
   block.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from fractions import Fraction
from typing import Any, Literal

from app.simulator.scorecard import display_pp, display_rate

Decision = Literal["passed", "failed", "inconclusive"]
Set = Literal["affected", "guard", "combined"]
MAX_FAILED_SHARE = Fraction(1, 5)


@dataclass(frozen=True)
class Thresholds:
    min_improvement_pp: Fraction
    max_regression_pp: Fraction
    min_sample: int


@dataclass(frozen=True)
class Counts:
    evaluator_id: str
    set: Set
    n: int
    control_passes: int
    treatment_passes: int
    version_mismatch: int = 0


@dataclass(frozen=True)
class Row:
    evaluator_id: str
    set: Set
    n: int
    control_passes: int
    treatment_passes: int
    version_mismatch: int
    control_rate: Fraction | None
    treatment_rate: Fraction | None
    delta: Fraction | None  # percentage points, exact
    blocking: bool = False
    insufficient_data: bool = False

    @property
    def delta_pp(self) -> float | None:
        return display_pp(self.delta)

    @property
    def control_rate_display(self) -> float | None:
        return display_rate(self.control_rate)

    @property
    def treatment_rate_display(self) -> float | None:
        return display_rate(self.treatment_rate)


@dataclass(frozen=True)
class RuleResult:
    decision: Decision
    reasons: list[dict[str, Any]] = field(default_factory=list)
    rows: list[Row] = field(default_factory=list)

    def headline(self, evaluator_id: str) -> Row | None:
        return next((r for r in self.rows if r.evaluator_id == evaluator_id and r.set == "affected"), None)


def _row(c: Counts) -> Row:
    control = Fraction(c.control_passes, c.n) if c.n else None
    treatment = Fraction(c.treatment_passes, c.n) if c.n else None
    delta = 100 * (treatment - control) if control is not None and treatment is not None else None
    return Row(
        c.evaluator_id,
        c.set,
        c.n,
        c.control_passes,
        c.treatment_passes,
        c.version_mismatch,
        control,
        treatment,
        delta,
    )


def _reason(code: str, row: Row | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {"code": code}
    if row is not None:
        out["evaluator_id"] = row.evaluator_id
        out["set"] = row.set
        out["n"] = row.n
        if row.delta is not None:
            out["delta_pp"] = row.delta_pp
    return out


def is_regression_check(row: Row, headline_id: str) -> bool:
    if row.evaluator_id == headline_id:
        return row.set == "guard"
    return row.set == "combined"


def evaluate(
    headline_id: str,
    counts: Sequence[Counts],
    *,
    treatment_runs_total: int,
    treatment_runs_failed: int,
    thresholds: Thresholds,
) -> RuleResult:
    rows = [_row(c) for c in counts]
    head = next((r for r in rows if r.evaluator_id == headline_id and r.set == "affected"), None)
    inconclusive: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    info: list[dict[str, Any]] = []

    if head is None or head.n < thresholds.min_sample:
        inconclusive.append(_reason("insufficient_sample", head) if head else {"code": "insufficient_sample"})
    if treatment_runs_total <= 0 or Fraction(treatment_runs_failed, treatment_runs_total) > MAX_FAILED_SHARE:
        reason = {"code": "too_many_failed_runs", "n": treatment_runs_total}
        inconclusive.append(reason)

    if head is not None and head.delta is not None and head.delta < thresholds.min_improvement_pp:
        failed.append(_reason("improvement_below_threshold", head))

    out_rows: list[Row] = []
    for r in rows:
        if not is_regression_check(r, headline_id):
            out_rows.append(r)
            continue
        if r.n < thresholds.min_sample:
            out_rows.append(_with(r, insufficient_data=True))
            info.append(_reason("insufficient_data", r))
            continue
        assert r.delta is not None
        blocking = r.delta < -thresholds.max_regression_pp
        out_rows.append(_with(r, blocking=blocking))
        if blocking:
            failed.append(_reason("regression", r))

    if inconclusive:
        decision: Decision = "inconclusive"
    elif failed:
        decision = "failed"
    else:
        decision = "passed"
    return RuleResult(decision, inconclusive + failed + info, out_rows)


def _with(r: Row, *, blocking: bool = False, insufficient_data: bool = False) -> Row:
    return Row(
        r.evaluator_id,
        r.set,
        r.n,
        r.control_passes,
        r.treatment_passes,
        r.version_mismatch,
        r.control_rate,
        r.treatment_rate,
        r.delta,
        blocking=blocking,
        insufficient_data=insufficient_data,
    )
