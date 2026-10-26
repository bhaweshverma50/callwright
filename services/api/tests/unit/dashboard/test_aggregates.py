"""Dashboard aggregation helpers (006 T041, FR-018 to FR-021)."""

from __future__ import annotations

from datetime import date

from app.dashboard.aggregates import bucket_starts, daily_average, delta_pp, top_with_others, zero_fill


def test_zero_fill_daily() -> None:
    rows = {date(2026, 10, 11): {"total_calls": 4}, date(2026, 10, 14): {"total_calls": 6}}
    series = zero_fill(rows, date(2026, 10, 10), date(2026, 10, 16), "day", {"total_calls": 0})
    assert [s["bucket_start"] for s in series][:2] == ["2026-10-10", "2026-10-11"]
    assert [s["total_calls"] for s in series] == [0, 4, 0, 0, 6, 0, 0]


def test_weekly_buckets_over_180_days() -> None:
    starts = bucket_starts(date(2026, 1, 1), date(2026, 7, 31), "week")
    assert starts[0] == date(2025, 12, 29)  # Monday of the first week
    assert all(d.weekday() == 0 for d in starts)
    assert starts[-1] <= date(2026, 7, 31) and len(starts) == 31


def test_daily_average_rounds_to_two_places() -> None:
    assert daily_average(10, 7) == 1.43
    assert daily_average(0, 30) == 0
    assert daily_average(5, 0) == 0


def test_top_ten_plus_others() -> None:
    rows = [(f"agt_{i}", f"Agent {i}", 100 - i) for i in range(12)]
    out = top_with_others(rows, 10)
    assert len(out) == 11
    assert out[-1]["agent_id"] == "others" and out[-1]["total_calls"] == (100 - 10) + (100 - 11)
    assert abs(sum(r["share"] for r in out) - 1) < 1e-9


def test_no_others_slice_when_ten_or_fewer() -> None:
    out = top_with_others([("agt_1", "A", 3), ("agt_2", "B", 1)], 10)
    assert [r["agent_id"] for r in out] == ["agt_1", "agt_2"] and out[0]["share"] == 0.75
    assert top_with_others([], 10) == []


def test_delta_pp() -> None:
    assert delta_pp(0.9, 0.8) == 10.0
    assert delta_pp(0.8333, 0.8) == 3.3
    assert delta_pp(None, 0.8) is None
    assert delta_pp(0.5, None) is None
