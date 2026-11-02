"""Run counts with manual overrides (008 T023; FR-008, FR-009, US1 scenario 5)."""

from __future__ import annotations

from app.test_runs.counts import ResultState, effective_status, newer_run, run_counts


def test_override_wins_over_the_judge() -> None:
    assert effective_status("failed", "passed") == "passed"
    assert effective_status("passed", "failed") == "failed"
    assert effective_status("error", "passed") == "passed"


def test_clearing_the_override_restores_the_judge_verdict() -> None:
    assert effective_status("failed", None) == "failed"
    assert effective_status(None, None) is None


def test_errors_count_separately_and_never_as_pass_or_fail() -> None:
    results = [
        ResultState("passed", None),
        ResultState("failed", None),
        ResultState("error", None),
        ResultState("error", None),
        ResultState(None, None),  # still running
    ]
    assert run_counts(results) == (1, 1, 2)


def test_counts_use_effective_status() -> None:
    results = [ResultState("failed", "passed"), ResultState("passed", None), ResultState("passed", "failed")]
    assert run_counts(results) == (2, 1, 0)
    cleared = [ResultState("failed", None), ResultState("passed", None), ResultState("passed", "failed")]
    assert run_counts(cleared) == (1, 2, 0)


def test_last_status_follows_the_latest_run_only() -> None:
    older, newer = "trn_01JA0000000000000000000000", "trn_01JB0000000000000000000000"
    assert newer_run(None, older)
    assert newer_run(older, newer)
    assert newer_run(newer, newer)  # an override on the latest run updates the case
    assert not newer_run(newer, older)  # an override on an older run does not
