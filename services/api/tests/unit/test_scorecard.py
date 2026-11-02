"""Scorecard math (008 T044, T060; research R8, SC-003). Written before ``simulator/scorecard.py``.

Verdict rows are keyed by the base call they belong to, so the original calls, a batch's
simulated calls and another batch's simulated calls line up by base call id.
"""

from __future__ import annotations

from fractions import Fraction

from app.simulator.scorecard import (
    ExcludedRun,
    ItemVerdict,
    VerdictRow,
    collapse,
    collapse_by_node,
    compute_scorecard,
    display_pp,
    display_rate,
    pair_verdicts,
    round_half_away,
)

INTENT = ("evl_intent", "intent_fulfillment", "Intent fulfilled")


def row(
    key: str,
    verdict: str | None,
    *,
    evaluator: tuple[str, str, str] = INTENT,
    version: int = 1,
    scope: str = "call",
    status: str = "completed",
    score: float | None = None,
    items: tuple[ItemVerdict, ...] = (),
) -> VerdictRow:
    return VerdictRow(
        key=key,
        evaluator_id=evaluator[0],
        evaluator_name=evaluator[1],
        evaluator_display_name=evaluator[2],
        evaluator_version=version,
        scope=scope,
        status=status,
        verdict=verdict,
        score=score,
        items=items,
    )


# Collapse ----------------------------------------------------------------------------------------


def test_call_scope_uses_the_run_verdict() -> None:
    assert collapse(row("c1", "pass")) == "pass"
    assert collapse(row("c1", "fail")) == "fail"


def test_errors_not_applicable_and_unfinished_runs_are_excluded() -> None:
    assert collapse(row("c1", None, status="error")) is None
    assert collapse(row("c1", None, status="skipped")) is None
    assert collapse(row("c1", None, status="pending")) is None
    assert collapse(row("c1", "not_applicable")) is None


def test_turn_scope_fails_when_any_turn_fails() -> None:
    items = (
        ItemVerdict(None, None, "pass", 1),
        ItemVerdict(None, None, "fail", -1),
        ItemVerdict(None, None, "pass", 1),
    )
    # The run itself passed (its max_failed_items tolerated one failure); the scorecard does not.
    assert collapse(row("c1", "pass", scope="turn", items=items)) == "fail"
    passing = (ItemVerdict(None, None, "pass", 1), ItemVerdict(None, None, "not_applicable", None))
    assert collapse(row("c1", "pass", scope="turn", items=passing)) == "pass"
    only_na = (ItemVerdict(None, None, "not_applicable", None),)
    assert collapse(row("c1", "pass", scope="turn", items=only_na)) is None


def test_turn_scope_without_items_falls_back_to_the_run_verdict() -> None:
    assert collapse(row("c1", "fail", scope="turn")) == "fail"


def test_flow_node_collapse_groups_items_by_node() -> None:
    items = (
        ItemVerdict("n1", "Greet", "pass", None),
        ItemVerdict("n2", "Book", "pass", None),
        ItemVerdict("n2", "Book", "fail", None),
        ItemVerdict("n3", "Close", "not_applicable", None),
    )
    by_node = collapse_by_node(row("c1", "fail", scope="flow_node", items=items))
    assert {k: v.verdict for k, v in by_node.items()} == {"n1": "pass", "n2": "fail"}
    assert by_node["n2"].label == "Book"
    assert collapse_by_node(row("c1", None, status="error", items=items)) == {}


# Pairing -----------------------------------------------------------------------------------------


def test_pairing_classifies_flips_and_unchanged() -> None:
    base = {"c1": ("fail", 1), "c2": ("pass", 1), "c3": ("pass", 1), "c4": ("fail", 1), "c5": ("pass", 1)}
    sim = {"c1": ("pass", 1), "c2": ("fail", 1), "c3": ("pass", 1), "c4": ("fail", 1), "c6": ("pass", 1)}
    pairs = pair_verdicts(base, sim)
    assert (pairs.n, pairs.improved, pairs.regressed, pairs.unchanged_pass, pairs.unchanged_fail) == (
        4,
        1,
        1,
        1,
        1,
    )
    assert pairs.version_mismatch == 0


def test_version_mismatch_is_left_out_of_pair_counts() -> None:
    pairs = pair_verdicts({"c1": ("fail", 1), "c2": ("pass", 2)}, {"c1": ("pass", 2), "c2": ("pass", 2)})
    assert pairs.n == 1 and pairs.unchanged_pass == 1 and pairs.improved == 0
    assert pairs.version_mismatch == 1


# Rounding ----------------------------------------------------------------------------------------


def test_rounding_is_half_away_from_zero_for_display_only() -> None:
    assert round_half_away(Fraction(1, 20), 1) == 0.1  # 0.05
    assert round_half_away(Fraction(-1, 20), 1) == -0.1
    assert round_half_away(Fraction(1, 8), 2) == 0.13  # 0.125
    assert display_pp(Fraction(30)) == 30.0
    assert display_pp(Fraction(-25, 2)) == -12.5
    assert display_pp(Fraction(-1, 20)) == -0.1
    assert display_rate(Fraction(2, 3)) == 0.6667
    assert display_rate(None) is None and display_pp(None) is None


def test_boundary_difference_is_exact() -> None:
    """0.7 - 0.6 is 10 percentage points exactly (floats give 9.999...)."""
    base = [row(f"c{i}", "pass" if i < 6 else "fail") for i in range(10)]
    sim = [row(f"c{i}", "pass" if i < 7 else "fail") for i in range(10)]
    card = compute_scorecard(keys=[f"c{i}" for i in range(10)], base_rows=base, sim_rows=sim)
    [r] = card.evaluators
    assert r.delta == Fraction(10)
    assert r.delta_pp == 10.0


# Aggregation ---------------------------------------------------------------------------------------


def spec_fixture() -> tuple[list[str], list[VerdictRow], list[VerdictRow]]:
    """US3 scenario 2: 10 base calls, 4 originals pass, 7 simulations pass, 3 improved."""
    keys = [f"c{i:02d}" for i in range(10)]
    base = [row(k, "pass" if i < 4 else "fail", score=0.9 if i < 4 else 0.2) for i, k in enumerate(keys)]
    sim = [row(k, "pass" if i < 7 else "fail", score=0.8 if i < 7 else 0.1) for i, k in enumerate(keys)]
    return keys, base, sim


def test_spec_fixture_forty_vs_seventy() -> None:
    keys, base, sim = spec_fixture()
    card = compute_scorecard(keys=keys, base_rows=base, sim_rows=sim)
    [r] = card.evaluators
    assert (r.base_n, r.base_passes, r.sim_n, r.sim_passes) == (10, 4, 10, 7)
    assert r.base_pass_rate == 0.4 and r.sim_pass_rate == 0.7
    assert r.delta_pp == 30.0
    assert (r.pairs.improved, r.pairs.regressed, r.pairs.unchanged_pass, r.pairs.unchanged_fail) == (
        3,
        0,
        4,
        3,
    )
    assert r.pairs.n == 10
    assert r.base_mean_score == round((0.9 * 4 + 0.2 * 6) / 10, 4)
    assert r.sim_mean_score == round((0.8 * 7 + 0.1 * 3) / 10, 4)
    assert card.base_call_count == 10 and card.sim_call_count == 10
    assert card.by_node == []


def test_zero_samples_give_null_rates() -> None:
    keys = ["c1", "c2"]
    base = [row("c1", None, status="error"), row("c2", "not_applicable")]
    sim = [row("c1", None, status="error")]
    card = compute_scorecard(keys=keys, base_rows=base, sim_rows=sim)
    [r] = card.evaluators
    assert (r.base_n, r.sim_n) == (0, 0)
    assert r.base_pass_rate is None and r.sim_pass_rate is None and r.delta_pp is None
    assert r.base_mean_score is None and r.sim_mean_score is None
    assert r.pairs.n == 0


def test_all_errors_on_one_side() -> None:
    keys = ["c1", "c2", "c3"]
    base = [row(k, "pass") for k in keys]
    sim = [row(k, None, status="error") for k in keys]
    [r] = compute_scorecard(keys=keys, base_rows=base, sim_rows=sim).evaluators
    assert r.base_pass_rate == 1.0 and r.sim_pass_rate is None and r.delta_pp is None
    assert r.pairs.n == 0


def test_ties_give_zero_change() -> None:
    keys = ["c1", "c2"]
    base = [row("c1", "pass"), row("c2", "fail")]
    sim = [row("c1", "fail"), row("c2", "pass")]
    [r] = compute_scorecard(keys=keys, base_rows=base, sim_rows=sim).evaluators
    assert r.delta_pp == 0.0 and r.delta == 0
    assert r.pairs.improved == 1 and r.pairs.regressed == 1


def test_failed_runs_are_excluded_from_the_simulated_side_and_listed() -> None:
    keys, base, sim = spec_fixture()
    failed = {"c08", "c09"}
    excluded = [ExcludedRun(f"srun_{k}", "failed", "insufficient credit") for k in sorted(failed)]
    card = compute_scorecard(
        keys=keys,
        base_rows=base,
        sim_rows=[r for r in sim if r.key not in failed],
        excluded_runs=excluded,
        sim_keys=[k for k in keys if k not in failed],
    )
    [r] = card.evaluators
    assert r.sim_n == 8 and r.base_n == 10
    assert card.sim_call_count == 8 and card.base_call_count == 10
    assert card.excluded_runs == excluded
    assert r.pairs.n == 8


def test_rows_from_keys_outside_the_batch_are_ignored() -> None:
    keys, base, sim = spec_fixture()
    stray = [row("other", "pass"), row("other2", "pass")]
    [r] = compute_scorecard(keys=keys, base_rows=base + stray, sim_rows=sim + stray).evaluators
    assert (r.base_n, r.sim_n) == (10, 10)


def test_rows_per_evaluator_sorted_by_display_name() -> None:
    keys = ["c1"]
    other = ("evl_a", "accuracy", "Accuracy")
    base = [row("c1", "pass"), row("c1", "fail", evaluator=other)]
    sim = [row("c1", "pass"), row("c1", "pass", evaluator=other)]
    card = compute_scorecard(keys=keys, base_rows=base, sim_rows=sim)
    assert [r.evaluator_display_name for r in card.evaluators] == ["Accuracy", "Intent fulfilled"]
    assert card.evaluators[0].pairs.improved == 1


def test_version_follows_the_simulated_side() -> None:
    """Base verdicts from an older evaluator version are not compared (R7)."""
    keys = ["c1", "c2"]
    base = [row("c1", "pass", version=1), row("c2", "fail", version=2)]
    sim = [row("c1", "pass", version=2), row("c2", "pass", version=2)]
    [r] = compute_scorecard(keys=keys, base_rows=base, sim_rows=sim).evaluators
    assert r.evaluator_version == 2
    assert (r.base_n, r.base_passes) == (1, 0)
    assert r.pairs.n == 1 and r.pairs.improved == 1 and r.pairs.version_mismatch == 1


def test_by_node_rows_for_flow_agents() -> None:
    keys = ["c1", "c2"]
    ev = ("evl_tc", "transition_correctness", "Transition correctness")

    def items(*pairs: tuple[str, str]) -> tuple[ItemVerdict, ...]:
        labels = {"n1": "Greet", "n2": "Book"}
        return tuple(ItemVerdict(n, labels[n], v, None) for n, v in pairs)

    base = [
        row("c1", "fail", evaluator=ev, scope="flow_node", items=items(("n1", "pass"), ("n2", "fail"))),
        row("c2", "fail", evaluator=ev, scope="flow_node", items=items(("n1", "fail"))),
    ]
    sim = [
        row("c1", "pass", evaluator=ev, scope="flow_node", items=items(("n1", "pass"), ("n2", "pass"))),
        row("c2", "pass", evaluator=ev, scope="flow_node", items=items(("n1", "pass"), ("n2", "pass"))),
    ]
    card = compute_scorecard(keys=keys, base_rows=base, sim_rows=sim)
    by = {(r.node_id, r.evaluator_id): r for r in card.by_node}
    n1 = by[("n1", "evl_tc")]
    assert n1.node_label == "Greet" and n1.scope == "flow_node"
    assert (n1.base_n, n1.base_passes, n1.sim_n, n1.sim_passes) == (2, 1, 2, 2)
    assert n1.delta_pp == 50.0 and n1.pairs.improved == 1 and n1.pairs.unchanged_pass == 1
    n2 = by[("n2", "evl_tc")]
    assert (n2.base_n, n2.sim_n) == (1, 2) and n2.pairs.n == 1 and n2.pairs.improved == 1
    assert [r.node_id for r in card.by_node] == ["n1", "n2"]


def test_experiment_baseline_is_matched_by_base_call_id() -> None:
    """Batch A's simulated calls as the baseline for batch B: rows already carry the base call
    id as key, so a batch-vs-batch scorecard is the same computation."""
    keys = ["c1", "c2", "c3"]
    batch_a = [row("c1", "pass"), row("c2", "fail"), row("c3", "fail")]
    batch_b = [row("c1", "pass"), row("c2", "pass"), row("c3", "fail")]
    card = compute_scorecard(keys=keys, base_rows=batch_a, sim_rows=batch_b, baseline="experiment")
    [r] = card.evaluators
    assert card.baseline == "experiment"
    assert r.base_pass_rate == round(1 / 3, 4) and r.sim_pass_rate == round(2 / 3, 4)
    assert r.delta == Fraction(100, 3) and r.delta_pp == 33.3
    assert r.pairs.improved == 1
