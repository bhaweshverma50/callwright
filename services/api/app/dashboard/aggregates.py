"""Pure dashboard helpers (006 T041): bucket starts, zero-fill, averages, top N plus "Others",
percentage-point deltas."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, timedelta
from typing import Any, Literal


def bucket_starts(start: date, end: date, bucket: Literal["day", "week"]) -> list[date]:
    """Every bucket start in ``[start, end]``; weeks start on Monday (``date_trunc('week')``)."""
    step = timedelta(days=1 if bucket == "day" else 7)
    current = start if bucket == "day" else start - timedelta(days=start.weekday())
    out: list[date] = []
    while current <= end:
        out.append(current)
        current += step
    return out


def zero_fill(
    rows: Mapping[date, Mapping[str, Any]],
    start: date,
    end: date,
    bucket: Literal["day", "week"],
    empty: Mapping[str, Any],
) -> list[dict[str, Any]]:
    return [
        {"bucket_start": d.isoformat(), **{**empty, **rows.get(d, {})}}
        for d in bucket_starts(start, end, bucket)
    ]


def daily_average(total: int, days: int) -> float:
    return round(total / days, 2) if days > 0 else 0


def top_with_others(rows: Sequence[tuple[str, str, int]], n: int) -> list[dict[str, Any]]:
    """``rows`` are (agent_id, agent_name, total_calls); the top ``n`` by calls, the rest as
    one "Others" slice. ``share`` is each slice's fraction of all calls."""
    ranked = sorted(rows, key=lambda r: (-r[2], r[1]))
    total = sum(r[2] for r in ranked)
    if total == 0:
        return []
    out = [
        {"agent_id": a, "agent_name": name, "total_calls": c, "share": c / total} for a, name, c in ranked[:n]
    ]
    rest = sum(r[2] for r in ranked[n:])
    if rest:
        out.append({"agent_id": "others", "agent_name": "Others", "total_calls": rest, "share": rest / total})
    return out


def delta_pp(rate: float | None, prior: float | None) -> float | None:
    if rate is None or prior is None:
        return None
    return round((rate - prior) * 100, 1)
