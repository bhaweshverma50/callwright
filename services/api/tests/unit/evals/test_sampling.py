"""Deterministic sampling (007 T079, FR-037). Charging and the not_sampled run state are covered
end to end in tests/integration/test_post_call_quality.py."""

from __future__ import annotations

from app.evals.sampling import applies, selected


def test_same_call_same_decision() -> None:
    assert all(
        selected("call_A", "intent_fulfillment", 20) == selected("call_A", "intent_fulfillment", 20)
        for _ in range(5)
    )


def test_roughly_rate_of_calls() -> None:
    picked = sum(selected(f"call_{i:05d}", "intent_fulfillment", 20) for i in range(1000))
    assert 160 <= picked <= 240
    small = sum(selected(f"call_{i:03d}", "intent_fulfillment", 20) for i in range(100))
    assert 10 <= small <= 30


def test_hundred_percent_always_and_per_evaluator() -> None:
    assert all(selected(f"call_{i}", "x", 100) for i in range(50))
    decisions = {(selected(f"call_{i}", "a", 50), selected(f"call_{i}", "b", 50)) for i in range(50)}
    assert len(decisions) > 1


def test_only_automatic_live_runs_are_sampled() -> None:
    assert applies("pipeline", "live")
    for trigger, origin in (
        ("rerun", "live"),
        ("dataset", "live"),
        ("simulation", "simulation"),
        ("pipeline", "test"),
    ):
        assert not applies(trigger, origin)
