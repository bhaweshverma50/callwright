"""Run queries and JSON views shared by the evals router, the quality port, review and
calibration. A call's *current* runs are its newest run per evaluator among the runs not yet
superseded (a rerun in flight keeps the previous result current until it completes)."""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.evals.models import EvaluatorResultItem, EvaluatorRun
from app.evals.scoring import EvalStatus, RunState, call_eval_status, run_counts
from app.evaluators.models import EvaluatorRow
from app.llms.client import billable_cost

LATEST_CURRENT = (
    "select distinct on (r.call_id, r.evaluator_id) r.* from evaluator_runs r "
    "where r.superseded_at is null {where} order by r.call_id, r.evaluator_id, r.created_at desc"
)


def split_current(runs: Sequence[EvaluatorRun]) -> tuple[list[EvaluatorRun], list[EvaluatorRun]]:
    """(current, history): newest unsuperseded run per evaluator, then everything else."""
    current: dict[str, EvaluatorRun] = {}
    for run in sorted(runs, key=lambda r: r.created_at, reverse=True):
        if run.superseded_at is None and run.evaluator_id not in current:
            current[run.evaluator_id] = run
    chosen = {r.id for r in current.values()}
    history = [r for r in sorted(runs, key=lambda r: r.created_at, reverse=True) if r.id not in chosen]
    return list(current.values()), history


def status_of(runs: Sequence[EvaluatorRun]) -> tuple[EvalStatus, int, int]:
    states = [RunState(r.status, r.verdict) for r in runs]  # type: ignore[arg-type]
    passes, fails = run_counts(states)
    return call_eval_status(states), passes, fails


def run_view(
    run: EvaluatorRun, row: EvaluatorRow | None, items: Sequence[EvaluatorResultItem]
) -> dict[str, Any]:
    charged = billable_cost(Decimal(run.raw_cost_usd)) if run.charge_txn_id else None
    return {
        "id": run.id,
        "evaluator_id": run.evaluator_id,
        "evaluator_name": row.name if row else run.evaluator_id,
        "evaluator_display_name": row.display_name if row else run.evaluator_id,
        "evaluator_version": run.evaluator_version,
        "scope": row.scope if row else "call",
        "trigger": run.trigger,
        "status": run.status,
        "skip_reason": run.skip_reason,
        "error": run.error,
        "verdict": run.verdict,
        "score": run.score,
        "rationale": run.rationale,
        "settings_snapshot": dict(run.settings_snapshot or {}),
        "judge_model": run.judge_model,
        "cost_usd": float(charged) if charged is not None else None,
        "items": [
            {
                "turn_index": i.turn_index,
                "flow_node_id": i.flow_node_id,
                "flow_node_label": i.flow_node_label,
                "start_ms": i.start_ms,
                "duration_ms": i.duration_ms,
                "verdict": i.verdict,
                "score": i.score,
                "rationale": i.rationale,
                "evidence": {
                    "turn_indices": list((i.evidence or {}).get("turn_indices") or []),
                    "quote": (i.evidence or {}).get("quote"),
                },
            }
            for i in items
        ],
        "created_at": run.created_at.isoformat(),
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        "superseded_at": run.superseded_at.isoformat() if run.superseded_at else None,
    }


async def call_runs(session: AsyncSession, call_id: str) -> list[EvaluatorRun]:
    return list(
        (await session.execute(select(EvaluatorRun).where(EvaluatorRun.call_id == call_id))).scalars()
    )


async def views_for(session: AsyncSession, runs: Sequence[EvaluatorRun]) -> list[dict[str, Any]]:
    if not runs:
        return []
    ids = [r.id for r in runs]
    items: dict[str, list[EvaluatorResultItem]] = {}
    for item in (
        await session.execute(
            select(EvaluatorResultItem)
            .where(EvaluatorResultItem.run_id.in_(ids))
            .order_by(EvaluatorResultItem.run_id, EvaluatorResultItem.position)
        )
    ).scalars():
        items.setdefault(item.run_id, []).append(item)
    rows = {
        r.id: r
        for r in (
            await session.execute(
                select(EvaluatorRow).where(EvaluatorRow.id.in_({r.evaluator_id for r in runs}))
            )
        ).scalars()
    }
    return [run_view(r, rows.get(r.evaluator_id), items.get(r.id, [])) for r in runs]


def ordered(views: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(views, key=lambda v: (str(v["evaluator_display_name"]).casefold(), v["created_at"]))
