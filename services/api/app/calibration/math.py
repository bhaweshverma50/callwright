"""Calibration math (007 T051, research R7; FR-026 to FR-030). Pure functions.

A pair is (evaluator verdict, resolved human label). A good label expects a pass:
both pass = pass and good; both fail = fail and bad; over-eager = fail and good;
missed = pass and bad.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Literal

Label = Literal["good", "bad", "conflict", "none"]
Reading = Literal["insufficient", "strong", "over_eager", "misses", "partial", "low"]
Direction = Literal["below_fails", "above_fails"]
THRESHOLDS = tuple(round(0.05 * k, 2) for k in range(1, 20))


def resolve_label(labels: Sequence[str]) -> Label:
    """Majority of the labels on a call; a tie is a conflict (FR-027)."""
    counts = Counter(label for label in labels if label in ("good", "bad"))
    if not counts:
        return "none"
    if counts["good"] == counts["bad"]:
        return "conflict"
    return "good" if counts["good"] > counts["bad"] else "bad"


@dataclass(frozen=True)
class Matrix:
    both_pass: int = 0
    both_fail: int = 0
    over_eager: int = 0
    missed: int = 0

    @property
    def n(self) -> int:
        return self.both_pass + self.both_fail + self.over_eager + self.missed

    @property
    def agreements(self) -> int:
        return self.both_pass + self.both_fail


def matrix(pairs: Iterable[tuple[str, str]]) -> Matrix:
    counts = Counter(pairs)
    return Matrix(
        counts[("pass", "good")], counts[("fail", "bad")], counts[("fail", "good")], counts[("pass", "bad")]
    )


def agreement(m: Matrix) -> float | None:
    return None if m.n == 0 else m.agreements / m.n


def wilson_interval(k: int, n: int, z: float = 1.96) -> tuple[float, float] | None:
    """Wilson score interval for k agreements out of n (95% by default)."""
    if n <= 0:
        return None
    p = k / n
    z2 = z * z
    denom = 1 + z2 / n
    center = (p + z2 / (2 * n)) / denom
    margin = z * math.sqrt(p * (1 - p) / n + z2 / (4 * n * n)) / denom
    return max(0.0, center - margin), min(1.0, center + margin)


def reading(m: Matrix, min_sample: int = 5) -> Reading:
    a = agreement(m)
    if m.n < min_sample or a is None:
        return "insufficient"
    if a >= 0.85:
        return "strong"
    if a < 0.5:
        return "low"
    if m.over_eager > 0 and m.over_eager >= 2 * m.missed:
        return "over_eager"
    if m.missed > 0 and m.missed >= 2 * m.over_eager:
        return "misses"
    return "partial"


def verdict_at(score: float, threshold: float, direction: Direction) -> str:
    if direction == "above_fails":
        return "fail" if score > threshold else "pass"
    return "pass" if score >= threshold else "fail"


def best_threshold(
    scored: Sequence[tuple[float, str]],
    *,
    current: float,
    direction: Direction = "below_fails",
    min_sample: int = 5,
) -> tuple[float, float] | None:
    """The 0.05-step threshold whose verdicts agree best with the labels, from stored scores only
    (FR-030); ties go to the threshold closest to ``current``, then the lower one."""
    usable = [(s, label) for s, label in scored if label in ("good", "bad")]
    if len(usable) < min_sample:
        return None
    best: tuple[float, float, float] | None = None  # (-agreement, distance, threshold)
    for t in THRESHOLDS:
        hits = sum(1 for s, label in usable if (verdict_at(s, t, direction) == "pass") == (label == "good"))
        key = (-hits / len(usable), round(abs(t - current), 6), t)
        if best is None or key < best:
            best = key
    assert best is not None
    return best[2], -best[0]


def agreement_at(scored: Sequence[tuple[float, str]], threshold: float, direction: Direction) -> float | None:
    usable = [(s, label) for s, label in scored if label in ("good", "bad")]
    if not usable:
        return None
    hits = sum(
        1 for s, label in usable if (verdict_at(s, threshold, direction) == "pass") == (label == "good")
    )
    return hits / len(usable)
