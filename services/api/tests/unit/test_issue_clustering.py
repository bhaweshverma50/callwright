"""Clustering and matching of evaluator failures (009 T014, T015, written before T018, T019;
spec FR-002, FR-004, SC-004, research R1)."""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

from app.issues.clustering import (
    Candidate,
    Failure,
    ResultRow,
    cluster_vectors,
    decide,
    failures_from,
    group_failures,
    keep_clusters,
    match_issue,
    origin_of,
)

NOW = datetime(2026, 11, 1, tzinfo=UTC)


def failure(
    call: str,
    *,
    evaluator: str = "evl_fact",
    node: str | None = None,
    origin: str = "live",
    version: str = "agv_1",
    ago: int = 0,
    reason: str = "quoted a price",
) -> Failure:
    return Failure(
        result_id=f"evr_{call}_{evaluator}_{node}",
        call_id=call,
        evaluator_id=evaluator,
        evaluator_version=1,
        node_id=node,
        node_label=node.upper() if node else None,
        reason=reason,
        call_origin=origin,
        agent_version_id=version,
        base_call_id=None,
        failed_at=NOW - timedelta(hours=ago),
    )


def unit(*values: float) -> list[float]:
    norm = math.sqrt(sum(v * v for v in values))
    return [v / norm for v in values]


# Turn collapse and grouping ----------------------------------------------------------------------


def row(**kw):  # type: ignore[no-untyped-def]
    base = dict(
        result_id="evr_1",
        call_id="call_1",
        evaluator_id="evl_x",
        evaluator_version=2,
        scope="call",
        verdict="fail",
        rationale="Run reason",
        items=(),
        call_origin="live",
        agent_version_id="agv_1",
        base_call_id=None,
        failed_at=NOW,
    )
    base.update(kw)
    return ResultRow(**base)


def test_call_scope_failure_is_one_row() -> None:
    [f] = failures_from([row()])
    assert (f.call_id, f.node_id, f.reason) == ("call_1", None, "Run reason")


def test_passing_runs_are_not_failures() -> None:
    assert failures_from([row(verdict="pass")]) == []


def test_turn_failures_collapse_to_one_row_per_call_joining_reasons() -> None:
    items = (
        (None, None, "fail", "Turn 1 interrupted"),
        (None, None, "pass", "fine"),
        (None, None, "fail", "Turn 3 interrupted"),
    )
    [f] = failures_from([row(scope="turn", items=items)])
    assert f.reason == "Turn 1 interrupted; Turn 3 interrupted"
    assert f.node_id is None


def test_node_items_give_one_failure_per_failing_node() -> None:
    items = (
        ("n_a", "Address", "fail", "Missed the zip"),
        ("n_a", "Address", "fail", "Missed the street"),
        ("n_b", "Booking", "pass", "ok"),
        ("n_c", "Close", "fail", "No goodbye"),
    )
    out = failures_from([row(scope="flow_node", items=items)])
    assert [(f.node_id, f.node_label, f.reason) for f in out] == [
        ("n_a", "Address", "Missed the zip; Missed the street"),
        ("n_c", "Close", "No goodbye"),
    ]


def test_grouping_by_evaluator_and_node_with_cap() -> None:
    fs = [failure(f"c{i}", ago=i) for i in range(5)]
    fs += [failure("d1", node="n_a"), failure("d2", evaluator="evl_other")]
    groups = group_failures(fs, cap=3)
    assert set(groups) == {("evl_fact", None), ("evl_fact", "n_a"), ("evl_other", None)}
    # The most recent first, capped.
    assert [f.call_id for f in groups[("evl_fact", None)]] == ["c0", "c1", "c2"]


# Clustering --------------------------------------------------------------------------------------


VECTORS = [unit(1, 0.05, 0), unit(1, 0, 0.05), unit(1, 0.02, 0.02), unit(0, 1, 0), unit(0, 1, 0.1)]


def test_clustering_is_deterministic_and_separates_patterns() -> None:
    first = cluster_vectors(VECTORS)
    assert first == cluster_vectors(VECTORS)
    assert sorted(sorted(c) for c in first) == [[0, 1, 2], [3, 4]]


def test_clustering_edge_sizes() -> None:
    assert cluster_vectors([]) == []
    assert cluster_vectors([unit(1, 0)]) == [[0]]


def test_keep_clusters_needs_three_distinct_calls_and_orders_by_size() -> None:
    fs = [failure("a"), failure("a"), failure("b"), failure("c"), failure("d"), failure("e")]
    clusters = [[0, 1, 2], [3, 4, 5]]  # first has only two distinct calls
    kept = keep_clusters(fs, clusters, min_calls=3)
    assert kept == [[3, 4, 5]]
    big = [failure(f"x{i}") for i in range(7)]
    assert keep_clusters(big, [[0, 1, 2], [3, 4, 5, 6]], min_calls=3) == [[3, 4, 5, 6], [0, 1, 2]]


# Matching ----------------------------------------------------------------------------------------


def candidate(issue: str, status: str, vec: list[float], applied_at: datetime | None = None) -> Candidate:
    return Candidate(issue, status, vec, applied_at)


def test_match_at_threshold_boundary() -> None:
    centroid = unit(1, 0)
    at = unit(0.85, math.sqrt(1 - 0.85**2))
    below = unit(0.84, math.sqrt(1 - 0.84**2))
    assert match_issue(centroid, [candidate("iss_at", "open", at)]) is not None
    assert match_issue(centroid, [candidate("iss_low", "open", below)]) is None


def test_match_prefers_live_issue_over_applied_one() -> None:
    centroid = unit(1, 0)
    applied = candidate("iss_old", "applied", unit(1, 0), NOW)
    recurrence = candidate("iss_new", "open", unit(1, 0.2))
    assert match_issue(centroid, [applied, recurrence]).issue_id == "iss_new"  # type: ignore[union-attr]
    assert match_issue(centroid, [applied]).issue_id == "iss_old"  # type: ignore[union-attr]


def test_decisions_by_status() -> None:
    fs = [failure(f"c{i}") for i in range(4)]
    assert decide(None, fs, {}).action == "create"
    for status in ("open", "validating", "validated"):
        assert decide(candidate("iss_1", status, unit(1)), fs, {}).action == "update"
    assert decide(candidate("iss_1", "dismissed", unit(1)), fs, {}).action == "counts_only"


def test_applied_issue_with_later_version_calls_yields_recurrence() -> None:
    applied_at = NOW - timedelta(days=2)
    created = {"agv_old": NOW - timedelta(days=10), "agv_new": applied_at}
    old = [failure(f"o{i}", version="agv_old") for i in range(3)]
    new = [failure(f"n{i}", version="agv_new") for i in range(3)]
    applied = candidate("iss_applied", "applied", unit(1), applied_at)
    result = decide(applied, old + new, created)
    assert result.action == "recurrence"
    assert {f.call_id for f in result.failures} == {"n0", "n1", "n2"}
    # Only calls from before the fix: the applied issue's counts only.
    assert decide(applied, old, created).action == "counts_only"
    # Fewer than three later calls is not yet a recurrence.
    assert decide(applied, [*old, *new[:2]], created).action == "counts_only"


def test_origin_thresholds() -> None:
    def fs(sim: int, live: int) -> list[Failure]:
        return [failure(f"s{i}", origin="simulation") for i in range(sim)] + [
            failure(f"l{i}") for i in range(live)
        ]

    assert origin_of(fs(8, 2)) == "simulated"
    assert origin_of(fs(2, 8)) == "real"
    assert origin_of(fs(5, 5)) == "mixed"
    assert origin_of(fs(0, 3)) == "real"
