"""Scorecard math (008 T049, T063; research R8). Pure functions over verdict rows.

Inputs are :class:`VerdictRow` values keyed by the base call they belong to (``key``), so the
original calls, a batch's simulated calls and another batch's simulated calls line up by base
call id. The router loads rows and serialises; 009 imports :func:`compute_scorecard` and
:func:`pair_verdicts` and compares the exact :class:`~fractions.Fraction` values
(``EvaluatorScore.base_rate``, ``sim_rate``, ``delta``), never the rounded display numbers.

Rules:

* A call's verdict for an evaluator: call and flow-node scope use the run verdict; turn scope
  collapses to ``fail`` if any turn fails, else ``pass`` when any turn applies (runs without
  items fall back to the run verdict). Runs that errored, were skipped or are unfinished, and
  ``not_applicable`` results, are excluded.
* Flow-node rows group a run's items by ``flow_node_id`` and collapse each node the same way.
* Pass rate ``passes / n`` (``None`` when ``n = 0``); ``delta_pp = 100 * (sim - base)``.
* Each row compares one evaluator version: the newest version on the simulated side (the
  baseline's when the simulated side has none). Rows of other versions are left out, and a
  call whose two sides were scored by different versions counts as ``version_mismatch`` and
  not as a pair.
* Display: rates with 4 decimals and ``delta_pp`` with 1, rounded half away from zero.
"""

from __future__ import annotations

import statistics
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from fractions import Fraction
from typing import Literal

Verdict = Literal["pass", "fail"]
Baseline = Literal["original", "experiment"]


@dataclass(frozen=True)
class ItemVerdict:
    node_id: str | None
    node_label: str | None
    verdict: str
    score: float | None


@dataclass(frozen=True)
class VerdictRow:
    """One current evaluator run of one call, keyed by its base call id."""

    key: str
    evaluator_id: str
    evaluator_name: str
    evaluator_display_name: str
    evaluator_version: int
    scope: str
    status: str
    verdict: str | None
    score: float | None
    items: tuple[ItemVerdict, ...] = ()


@dataclass(frozen=True)
class NodeVerdict:
    verdict: Verdict
    label: str | None
    score: float | None


@dataclass(frozen=True)
class PairCounts:
    n: int = 0
    improved: int = 0
    regressed: int = 0
    unchanged_pass: int = 0
    unchanged_fail: int = 0
    version_mismatch: int = 0


@dataclass(frozen=True)
class ExcludedRun:
    simulation_run_id: str
    status: str
    error_message: str | None


@dataclass(frozen=True)
class EvaluatorScore:
    evaluator_id: str
    evaluator_name: str
    evaluator_display_name: str
    evaluator_version: int
    scope: str
    node_id: str | None
    node_label: str | None
    base_n: int
    base_passes: int
    sim_n: int
    sim_passes: int
    base_rate: Fraction | None
    sim_rate: Fraction | None
    delta: Fraction | None
    base_mean_score: float | None
    sim_mean_score: float | None
    pairs: PairCounts

    @property
    def base_pass_rate(self) -> float | None:
        return display_rate(self.base_rate)

    @property
    def sim_pass_rate(self) -> float | None:
        return display_rate(self.sim_rate)

    @property
    def delta_pp(self) -> float | None:
        return display_pp(self.delta)


@dataclass(frozen=True)
class Scorecard:
    baseline: Baseline
    base_call_count: int
    sim_call_count: int
    excluded_runs: list[ExcludedRun]
    evaluators: list[EvaluatorScore]
    by_node: list[EvaluatorScore] = field(default_factory=list)


def round_half_away(value: Fraction, places: int) -> float:
    """Round an exact value half away from zero (display only)."""
    exact = Decimal(value.numerator) / Decimal(value.denominator)
    return float(exact.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP))


def display_rate(value: Fraction | None) -> float | None:
    return None if value is None else round_half_away(value, 4)


def display_pp(value: Fraction | None) -> float | None:
    return None if value is None else round_half_away(value, 1)


def _fold(verdicts: Iterable[str]) -> Verdict | None:
    seen = [v for v in verdicts if v in ("pass", "fail")]
    if not seen:
        return None
    return "fail" if "fail" in seen else "pass"


def collapse(row: VerdictRow) -> Verdict | None:
    """The call's verdict for this run, or None when it does not count."""
    if row.status != "completed" or row.verdict not in ("pass", "fail"):
        return None
    if row.scope == "turn" and row.items:
        return _fold(i.verdict for i in row.items)
    return "pass" if row.verdict == "pass" else "fail"


def collapse_by_node(row: VerdictRow) -> dict[str, NodeVerdict]:
    """Per flow node: fail if any of its items fails, else pass when any applies."""
    if row.status != "completed":
        return {}
    grouped: dict[str, list[ItemVerdict]] = {}
    for item in row.items:
        if item.node_id:
            grouped.setdefault(item.node_id, []).append(item)
    out: dict[str, NodeVerdict] = {}
    for node_id, items in grouped.items():
        verdict = _fold(i.verdict for i in items)
        if verdict is None:
            continue
        label = next((i.node_label for i in items if i.node_label), None)
        scores = [i.score for i in items if i.score is not None and i.verdict in ("pass", "fail")]
        out[node_id] = NodeVerdict(verdict, label, statistics.fmean(scores) if scores else None)
    return out


def pair_verdicts(base: Mapping[str, tuple[str, int]], sim: Mapping[str, tuple[str, int]]) -> PairCounts:
    """Pairs of ``key -> (verdict, evaluator version)`` present on both sides."""
    n = improved = regressed = up = down = mismatch = 0
    for key, (sim_verdict, sim_version) in sim.items():
        if key not in base:
            continue
        base_verdict, base_version = base[key]
        if base_version != sim_version:
            mismatch += 1
            continue
        n += 1
        if base_verdict == "fail" and sim_verdict == "pass":
            improved += 1
        elif base_verdict == "pass" and sim_verdict == "fail":
            regressed += 1
        elif sim_verdict == "pass":
            up += 1
        else:
            down += 1
    return PairCounts(n, improved, regressed, up, down, mismatch)


@dataclass
class _Side:
    """Verdicts of one side for one (evaluator, node) row: ``key -> (verdict, version, score)``."""

    values: dict[str, tuple[Verdict, int, float | None]] = field(default_factory=dict)

    def at(self, version: int) -> dict[str, tuple[Verdict, float | None]]:
        return {k: (v, s) for k, (v, ver, s) in self.values.items() if ver == version}


@dataclass
class _Group:
    evaluator_id: str
    name: str
    display: str
    scope: str
    node_id: str | None = None
    node_label: str | None = None
    base: _Side = field(default_factory=_Side)
    sim: _Side = field(default_factory=_Side)


def _mean(scores: Sequence[float | None]) -> float | None:
    values = [s for s in scores if s is not None]
    return round(statistics.fmean(values), 4) if values else None


def _rate(passes: int, n: int) -> Fraction | None:
    return Fraction(passes, n) if n else None


def _score(group: _Group) -> EvaluatorScore:
    versions = {ver for _, ver, _ in group.sim.values.values()} or {
        ver for _, ver, _ in group.base.values.values()
    }
    version = max(versions) if versions else 0
    base = group.base.at(version)
    sim = group.sim.at(version)
    base_passes = sum(1 for v, _ in base.values() if v == "pass")
    sim_passes = sum(1 for v, _ in sim.values() if v == "pass")
    base_rate = _rate(base_passes, len(base))
    sim_rate = _rate(sim_passes, len(sim))
    delta = 100 * (sim_rate - base_rate) if base_rate is not None and sim_rate is not None else None
    pairs = pair_verdicts(
        {k: (v, ver) for k, (v, ver, _) in group.base.values.items()},
        {k: (v, ver) for k, (v, ver, _) in group.sim.values.items() if ver == version},
    )
    return EvaluatorScore(
        evaluator_id=group.evaluator_id,
        evaluator_name=group.name,
        evaluator_display_name=group.display,
        evaluator_version=version,
        scope=group.scope,
        node_id=group.node_id,
        node_label=group.node_label,
        base_n=len(base),
        base_passes=base_passes,
        sim_n=len(sim),
        sim_passes=sim_passes,
        base_rate=base_rate,
        sim_rate=sim_rate,
        delta=delta,
        base_mean_score=_mean([s for _, s in base.values()]),
        sim_mean_score=_mean([s for _, s in sim.values()]),
        pairs=pairs,
    )


def compute_scorecard(
    *,
    keys: Sequence[str],
    base_rows: Sequence[VerdictRow],
    sim_rows: Sequence[VerdictRow],
    excluded_runs: Sequence[ExcludedRun] = (),
    sim_keys: Sequence[str] | None = None,
    baseline: Baseline = "original",
) -> Scorecard:
    """Scorecard over the batch's base calls ``keys``.

    ``sim_keys`` are the base calls whose simulation completed (default: all ``keys``); simulated
    rows of other keys are ignored, as are baseline rows outside ``keys``.
    """
    batch = set(keys)
    completed = set(sim_keys) if sim_keys is not None else batch
    groups: dict[tuple[str, str | None], _Group] = {}

    def group(r: VerdictRow, node_id: str | None = None, label: str | None = None) -> _Group:
        found = groups.get((r.evaluator_id, node_id))
        if found is None:
            found = _Group(
                r.evaluator_id,
                r.evaluator_name,
                r.evaluator_display_name,
                "flow_node" if node_id else r.scope,
                node_id,
                label,
            )
            groups[(r.evaluator_id, node_id)] = found
        if label and not found.node_label:
            found.node_label = label
        return found

    for side, rows, allowed in (("base", base_rows, batch), ("sim", sim_rows, completed & batch)):
        for r in rows:
            if r.key not in allowed:
                continue
            verdict = collapse(r)
            target = group(r)  # every evaluator gets a row, even with n = 0
            bucket = target.base if side == "base" else target.sim
            if verdict is not None:
                bucket.values[r.key] = (verdict, r.evaluator_version, r.score)
            for node_id, nv in collapse_by_node(r).items():
                node_group = group(r, node_id, nv.label)
                node_bucket = node_group.base if side == "base" else node_group.sim
                node_bucket.values[r.key] = (nv.verdict, r.evaluator_version, nv.score)

    evaluators = sorted(
        (_score(g) for (_, node), g in groups.items() if node is None),
        key=lambda s: (s.evaluator_display_name.casefold(), s.evaluator_id),
    )
    by_node = sorted(
        (_score(g) for (_, node), g in groups.items() if node is not None),
        key=lambda s: (s.node_id or "", s.evaluator_display_name.casefold(), s.evaluator_id),
    )
    return Scorecard(
        baseline=baseline,
        base_call_count=len(batch),
        sim_call_count=len(completed & batch),
        excluded_runs=list(excluded_runs),
        evaluators=evaluators,
        by_node=by_node,
    )
