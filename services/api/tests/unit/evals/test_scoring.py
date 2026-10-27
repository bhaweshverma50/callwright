"""Run verdict aggregation and call evaluation status (007 T006, FR-015, FR-016). Written first."""

from __future__ import annotations

import pytest

from app.evals.scoring import (
    ItemOutcome,
    RunState,
    call_eval_status,
    judge_item_verdict,
    process_reward_verdict,
    run_counts,
    run_verdict,
)

P, F, NA = "pass", "fail", "not_applicable"


def items(*pairs: tuple[str, float | None]) -> list[ItemOutcome]:
    return [ItemOutcome(v, s) for v, s in pairs]  # type: ignore[arg-type]


class TestRunVerdict:
    def test_call_scope_single_pass(self) -> None:
        assert run_verdict(items((P, 0.9))) == (P, 0.9)

    def test_call_scope_single_fail(self) -> None:
        assert run_verdict(items((F, 0.2))) == (F, 0.2)

    def test_no_items_is_not_applicable(self) -> None:
        assert run_verdict([]) == (NA, None)

    def test_all_not_applicable(self) -> None:
        assert run_verdict(items((NA, None), (NA, None))) == (NA, None)

    def test_turn_scope_one_failure_fails_by_default(self) -> None:
        verdict, score = run_verdict(items((P, 1.0), (F, 0.0), (P, 1.0)))
        assert verdict == F
        assert score == pytest.approx(2 / 3)

    def test_allowed_failures(self) -> None:
        rows = items((P, 1.0), (F, 0.0), (P, 1.0))
        assert run_verdict(rows, max_failed_items=1)[0] == P
        assert run_verdict(items((F, 0.0), (F, 0.0), (P, 1.0)), max_failed_items=1)[0] == F

    def test_mean_excludes_not_applicable_and_missing_scores(self) -> None:
        verdict, score = run_verdict(items((P, 0.8), (NA, None), (P, None), (F, 0.2)), max_failed_items=1)
        assert verdict == P
        assert score == pytest.approx(0.5)

    def test_applicable_without_scores(self) -> None:
        assert run_verdict(items((P, None))) == (P, None)

    def test_process_reward_items(self) -> None:
        rows = [ItemOutcome(process_reward_verdict(s), float(s)) for s in (1, 0, -1, 1)]
        assert [r.verdict for r in rows] == [P, P, F, P]
        verdict, score = run_verdict(rows)
        assert verdict == F
        assert score == pytest.approx(0.25)
        assert run_verdict([ItemOutcome(process_reward_verdict(s), float(s)) for s in (0, 1)]) == (P, 0.5)


class TestJudgeCutoff:
    @pytest.mark.parametrize(("score", "expected"), [(0.5, P), (0.49, F), (1.0, P), (0.0, F), (0.5000001, P)])
    def test_score_at_cutoff_passes(self, score: float, expected: str) -> None:
        assert judge_item_verdict(score, 0.5) == expected


def run(status: str, verdict: str | None = None) -> RunState:
    return RunState(status, verdict)  # type: ignore[arg-type]


class TestCallEvalStatus:
    def test_no_runs(self) -> None:
        assert call_eval_status([]) == "not_evaluated"

    def test_any_pending_or_running_is_running(self) -> None:
        assert call_eval_status([run("completed", F), run("pending")]) == "running"
        assert call_eval_status([run("running"), run("error")]) == "running"

    def test_failed_beats_passed(self) -> None:
        assert call_eval_status([run("completed", P), run("completed", F)]) == "failed"

    def test_passed(self) -> None:
        assert call_eval_status([run("completed", P), run("skipped"), run("error")]) == "passed"

    def test_completed_not_applicable_counts_as_passed(self) -> None:
        assert call_eval_status([run("completed", NA)]) == "passed"

    def test_only_errors(self) -> None:
        assert call_eval_status([run("error"), run("skipped")]) == "error"

    def test_only_skipped_is_not_evaluated(self) -> None:
        # Every check skipped (not sampled, no credit): nothing was evaluated, nothing failed.
        assert call_eval_status([run("skipped"), run("skipped")]) == "not_evaluated"

    def test_counts(self) -> None:
        runs = [run("completed", P), run("completed", F), run("completed", NA), run("completed", P)]
        assert run_counts(runs) == (2, 1)
