"""Keep rule (009 T035, written before T037; spec FR-014, SC-002, research R3)."""

from __future__ import annotations

from fractions import Fraction

import pytest

from app.issues.validation_rule import Counts, Thresholds, evaluate

H = "evl_headline"
OTHER = "evl_tools"
DEFAULT = Thresholds(min_improvement_pp=Fraction(10), max_regression_pp=Fraction(5), min_sample=5)


def headline(n: int, control: int, treatment: int, *, mismatch: int = 0) -> Counts:
    return Counts(H, "affected", n, control, treatment, version_mismatch=mismatch)


def run(*counts: Counts, total: int = 10, failed: int = 0, thresholds: Thresholds = DEFAULT):  # type: ignore[no-untyped-def]
    return evaluate(
        H, list(counts), treatment_runs_total=total, treatment_runs_failed=failed, thresholds=thresholds
    )


def codes(result) -> list[str]:  # type: ignore[no-untyped-def]
    return [r["code"] for r in result.reasons]


def row(result, evaluator: str, set_: str):  # type: ignore[no-untyped-def]
    return next(r for r in result.rows if r.evaluator_id == evaluator and r.set == set_)


def test_clear_improvement_passes_with_exact_delta() -> None:
    result = run(headline(10, 2, 6))
    assert result.decision == "passed"
    assert codes(result) == []
    head = row(result, H, "affected")
    assert head.delta == Fraction(40)
    assert head.delta_pp == 40.0
    assert head.control_rate == Fraction(1, 5)
    assert head.treatment_rate == Fraction(3, 5)


def test_small_improvement_fails() -> None:
    result = run(headline(20, 4, 5), total=20)
    assert result.decision == "failed"
    assert codes(result) == ["improvement_below_threshold"]
    assert result.reasons[0]["delta_pp"] == 5.0
    assert result.reasons[0]["evaluator_id"] == H


def test_exactly_ten_points_passes() -> None:
    result = run(headline(10, 2, 3))
    assert result.decision == "passed"


def test_just_below_ten_points_fails() -> None:
    # 1/11 is 9.09 points: below the threshold even though it rounds near it.
    result = run(headline(11, 0, 1), total=11)
    assert result.decision == "failed"


def test_regression_at_exactly_five_points_does_not_block() -> None:
    result = run(headline(10, 2, 6), Counts(OTHER, "combined", 20, 20, 19))
    assert result.decision == "passed"
    assert not row(result, OTHER, "combined").blocking


def test_regression_of_eight_points_blocks() -> None:
    other = Counts(OTHER, "combined", 25, 25, 23)  # -8.0 points
    result = run(headline(10, 2, 5), other)
    assert result.decision == "failed"
    assert codes(result) == ["regression"]
    reason = result.reasons[0]
    assert reason["evaluator_id"] == OTHER
    assert reason["set"] == "combined"
    assert reason["delta_pp"] == -8.0
    assert reason["n"] == 25
    assert row(result, OTHER, "combined").blocking


def test_regression_below_min_sample_is_informational() -> None:
    result = run(headline(10, 2, 6), Counts(OTHER, "combined", 4, 4, 0))
    assert result.decision == "passed"
    assert codes(result) == ["insufficient_data"]
    other = row(result, OTHER, "combined")
    assert other.insufficient_data and not other.blocking


def test_headline_below_min_sample_is_inconclusive() -> None:
    result = run(headline(4, 0, 4))
    assert result.decision == "inconclusive"
    assert "insufficient_sample" in codes(result)


def test_headline_at_min_sample_counts() -> None:
    result = run(headline(5, 0, 5))
    assert result.decision == "passed"


def test_too_many_failed_runs_is_inconclusive() -> None:
    result = run(headline(10, 2, 6), total=10, failed=3)
    assert result.decision == "inconclusive"
    assert "too_many_failed_runs" in codes(result)


def test_exactly_twenty_percent_failed_runs_is_allowed() -> None:
    result = run(headline(8, 1, 6), total=10, failed=2)
    assert result.decision == "passed"


def test_no_treatment_runs_is_inconclusive() -> None:
    result = run(headline(0, 0, 0), total=0)
    assert result.decision == "inconclusive"


def test_headline_regression_on_guard_set_blocks() -> None:
    guard = Counts(H, "guard", 10, 10, 8)  # -20 points on calls that used to pass
    result = run(headline(10, 2, 8), guard)
    assert result.decision == "failed"
    assert codes(result) == ["regression"]
    assert result.reasons[0]["set"] == "guard"


def test_headline_combined_row_is_not_a_regression_check() -> None:
    # The headline is judged on affected (improvement) and guard (regression) only.
    result = run(headline(10, 2, 6), Counts(H, "combined", 20, 12, 10))
    assert result.decision == "passed"


def test_other_evaluator_affected_and_guard_rows_are_informational() -> None:
    result = run(
        headline(10, 2, 6),
        Counts(OTHER, "affected", 10, 10, 2),
        Counts(OTHER, "guard", 10, 10, 2),
        Counts(OTHER, "combined", 20, 20, 19),
    )
    assert result.decision == "passed"
    assert not row(result, OTHER, "affected").blocking


def test_custom_thresholds_are_respected() -> None:
    strict = Thresholds(min_improvement_pp=Fraction(50), max_regression_pp=Fraction(0), min_sample=10)
    assert run(headline(10, 2, 6), thresholds=strict).decision == "failed"  # +40 < +50
    loose = Thresholds(min_improvement_pp=Fraction(5), max_regression_pp=Fraction(20), min_sample=3)
    result = run(headline(20, 4, 5), Counts(OTHER, "combined", 10, 10, 9), total=20, thresholds=loose)
    assert result.decision == "passed"  # +5 >= +5 and -10 within -20
    zero = Thresholds(min_improvement_pp=Fraction(10), max_regression_pp=Fraction(0), min_sample=5)
    result = run(headline(10, 2, 6), Counts(OTHER, "combined", 20, 20, 19), thresholds=zero)
    assert result.decision == "failed"  # any drop blocks at 0
    assert run(headline(10, 2, 6), thresholds=strict).reasons[0]["code"] == "improvement_below_threshold"


def test_version_mismatches_are_reported_not_counted() -> None:
    result = run(headline(5, 1, 5, mismatch=3))
    head = row(result, H, "affected")
    assert head.n == 5 and head.version_mismatch == 3
    assert result.decision == "passed"


def test_missing_headline_row_is_inconclusive() -> None:
    result = run(Counts(OTHER, "combined", 10, 5, 5))
    assert result.decision == "inconclusive"
    assert codes(result)[0] == "insufficient_sample"


def test_inconclusive_wins_over_failed() -> None:
    result = run(headline(4, 4, 0), total=10, failed=5)
    assert result.decision == "inconclusive"


@pytest.mark.parametrize(
    ("control", "treatment", "expected"),
    [(0, 1, "passed"), (1, 1, "failed"), (2, 3, "passed"), (9, 10, "passed"), (10, 10, "failed")],
)
def test_boundaries_over_ten_calls(control: int, treatment: int, expected: str) -> None:
    assert run(headline(10, control, treatment)).decision == expected


def test_rows_carry_display_values() -> None:
    result = run(headline(3, 1, 2), thresholds=Thresholds(Fraction(10), Fraction(5), 3), total=3)
    head = row(result, H, "affected")
    assert head.delta_pp == 33.3
    assert head.control_rate_display == 0.3333
    assert head.treatment_rate_display == 0.6667


def test_checks_without_any_verdict_add_no_reason() -> None:
    result = run(headline(10, 2, 6), Counts(OTHER, "combined", 0, 0, 0))
    assert result.decision == "passed" and codes(result) == []
    assert row(result, OTHER, "combined").insufficient_data
