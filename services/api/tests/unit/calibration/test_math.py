"""Calibration math reference set (007 T048, SC-004, research R7). Written before math.py."""

from __future__ import annotations

import pytest

from app.calibration.math import (
    Matrix,
    agreement,
    best_threshold,
    matrix,
    reading,
    resolve_label,
    wilson_interval,
)

P, F = "pass", "fail"
G, B = "good", "bad"


def pairs(both_pass: int, both_fail: int, over_eager: int, missed: int) -> list[tuple[str, str]]:
    return [(P, G)] * both_pass + [(F, B)] * both_fail + [(F, G)] * over_eager + [(P, B)] * missed


# (both_pass, both_fail, over_eager, missed, agreement, reading): the 20-case reference table.
REFERENCE = [
    (4, 2, 2, 2, 0.6, "partial"),  # US4 seed
    (2, 2, 0, 0, 1.0, "insufficient"),  # n = 4 is under the minimum
    (3, 2, 0, 0, 1.0, "strong"),  # n = 5 is enough
    (17, 0, 2, 1, 0.85, "strong"),  # exactly 85%
    (16, 0, 2, 2, 0.8, "partial"),
    (3, 3, 4, 0, 0.6, "over_eager"),  # US4 scenario 3
    (3, 3, 0, 4, 0.6, "misses"),
    (3, 3, 2, 1, 6 / 9, "over_eager"),  # exactly twice
    (3, 3, 1, 2, 6 / 9, "misses"),
    (3, 3, 3, 2, 0.5454545, "partial"),  # 1.5x, neither rule
    (5, 0, 5, 0, 0.5, "over_eager"),  # 0.5 is not low
    (4, 0, 5, 0, 4 / 9, "low"),  # under 0.5 is low whatever the split
    (0, 0, 3, 3, 0.0, "low"),
    (10, 10, 0, 0, 1.0, "strong"),
    (0, 0, 0, 0, None, "insufficient"),
    (1, 1, 1, 1, 0.5, "insufficient"),
    (6, 0, 2, 2, 0.6, "partial"),
    (2, 4, 0, 3, 6 / 9, "misses"),
    (7, 1, 1, 1, 0.8, "partial"),
    (40, 45, 10, 5, 0.85, "strong"),
]


@pytest.mark.parametrize(("bp", "bf", "oe", "mi", "rate", "expected"), REFERENCE)
def test_reference_table(bp: int, bf: int, oe: int, mi: int, rate: float | None, expected: str) -> None:
    m = matrix(pairs(bp, bf, oe, mi))
    assert (m.both_pass, m.both_fail, m.over_eager, m.missed, m.n) == (bp, bf, oe, mi, bp + bf + oe + mi)
    a = agreement(m)
    if rate is None:
        assert a is None
    else:
        assert a == pytest.approx(rate, abs=1e-6)
    assert reading(m, min_sample=5) == expected


def test_wilson_interval_known_value() -> None:
    low, high = wilson_interval(6, 10)  # type: ignore[misc]
    assert low == pytest.approx(0.313, abs=0.001) and high == pytest.approx(0.832, abs=0.001)
    assert wilson_interval(0, 0) is None
    low, high = wilson_interval(10, 10)  # type: ignore[misc]
    assert high == pytest.approx(1.0) and 0.7 < low < 0.75
    low, high = wilson_interval(0, 5)  # type: ignore[misc]
    assert low == pytest.approx(0.0, abs=1e-12)


@pytest.mark.parametrize(
    ("labels", "expected"),
    [
        ([], "none"),
        ([G], "good"),
        ([B], "bad"),
        ([G, B], "conflict"),
        ([G, G, B], "good"),
        ([B, B, G, G], "conflict"),
        ([B, B, G], "bad"),
    ],
)
def test_resolve_label(labels: list[str], expected: str) -> None:
    assert resolve_label(labels) == expected


def test_matrix_ignores_unknown_pairs() -> None:
    m = matrix([(P, G), ("not_applicable", G), (F, "conflict"), (F, B)])
    assert m == Matrix(1, 1, 0, 0)


class TestBestThreshold:
    def test_needs_minimum_sample(self) -> None:
        assert best_threshold([(0.9, G)] * 4, current=0.5) is None

    def test_finds_threshold_that_agrees_best(self) -> None:
        scored = [(0.9, G), (0.8, G), (0.62, G), (0.6, B), (0.3, B), (0.2, B)]
        t, a = best_threshold(scored, current=0.5)  # type: ignore[misc]
        # No 0.05 step falls between 0.60 and 0.62, so the best is 5 of 6 and 0.50 ties for it.
        assert a == pytest.approx(5 / 6) and t == pytest.approx(0.5)

    def test_perfect_split_with_tie_breaking_toward_current(self) -> None:
        scored = [(0.9, G), (0.85, G), (0.8, G), (0.2, B), (0.15, B), (0.1, B)]
        # Thresholds 0.25 to 0.80 all agree 100%; the one closest to 0.7 wins.
        assert best_threshold(scored, current=0.7) == (pytest.approx(0.7), 1.0)
        # Equal distance to two candidates picks the lower one.
        assert best_threshold(scored, current=0.725) == (pytest.approx(0.7), 1.0)

    def test_above_fails_direction(self) -> None:
        # Anomaly distance: a high score fails, so good calls sit low.
        scored = [(0.1, G), (0.2, G), (0.3, G), (0.8, B), (0.9, B), (0.95, B)]
        t, a = best_threshold(scored, current=0.7, direction="above_fails")  # type: ignore[misc]
        assert a == 1.0 and 0.3 <= t < 0.8
        assert t == pytest.approx(0.7)

    def test_inverted_scores_tie_at_half(self) -> None:
        scored = [(0.4, G)] * 5 + [(0.6, B)] * 5
        t, a = best_threshold(scored, current=0.5)  # type: ignore[misc]
        # Good calls score low here, so no threshold beats 50%; of the tied ones 0.40 is closest.
        assert a == pytest.approx(0.5) and t == pytest.approx(0.4)
