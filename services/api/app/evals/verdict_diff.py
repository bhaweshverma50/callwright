"""Verdict differences between two calls (007 T040, T041; FR-020): one row per evaluator with a
current completed run on either call."""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.calls.quality_port import VerdictDiff
from app.evals.views import current_runs_sql


async def diffs(
    session: AsyncSession, left_call_id: str, right_call_id: str
) -> list[tuple[VerdictDiff, str, dict[str, int | None]]]:
    """(diff, display name, {left version, right version}) per evaluator, ordered by display name."""
    sql = (
        "select cur.call_id, cur.evaluator_id, cur.evaluator_version, cur.verdict, cur.score, cur.rationale, "  # noqa: S608
        "e.name, e.display_name from ("
        + current_runs_sql("and r.call_id = any(:ids) and r.status = 'completed'")
        + ") cur join evaluators e on e.id = cur.evaluator_id"
    )
    rows = (await session.execute(text(sql), {"ids": [left_call_id, right_call_id]})).all()
    by_eval: dict[str, dict[str, object]] = {}
    for call_id, evaluator_id, version, verdict, score, rationale, name, display in rows:
        side = "left" if call_id == left_call_id else "right"
        entry = by_eval.setdefault(evaluator_id, {"name": name, "display": display})
        entry[side] = (verdict, score, rationale, version)
    out = []
    for evaluator_id, entry in by_eval.items():
        left = entry.get("left") or (None, None, None, None)
        right = entry.get("right") or (None, None, None, None)
        assert isinstance(left, tuple) and isinstance(right, tuple)
        diff = VerdictDiff(
            evaluator_id=evaluator_id,
            evaluator_name=str(entry["name"]),
            left_verdict=left[0],
            left_score=float(left[1]) if left[1] is not None else None,
            right_verdict=right[0],
            right_score=float(right[1]) if right[1] is not None else None,
            right_rationale=right[2],
        )
        out.append((diff, str(entry["display"]), {"left": left[3], "right": right[3]}))
    return sorted(out, key=lambda t: t[1].casefold())


async def verdict_diffs(
    session: AsyncSession, left_call_id: str, right_call_id: str
) -> Sequence[VerdictDiff]:
    return [d for d, _, _ in await diffs(session, left_call_id, right_call_id)]
