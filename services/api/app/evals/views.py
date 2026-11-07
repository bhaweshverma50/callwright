"""The one "current run" rule and the run views shared by the evals router, the quality port,
review, calibration, 008 and 009.

A call's *current* runs are its newest run per evaluator among the runs not yet superseded.
``current_runs_sql`` states the rule for SQL readers, ``split_current`` for loaded rows,
``eval_status_sql`` and ``call_statuses`` derive a call's evaluation status from them exactly as
``scoring.call_eval_status`` does."""

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


def current_runs_sql(where: str = "", *, columns: str = "r.*", join_calls: bool = False) -> str:
    """SQL selecting current runs (alias ``r``; ``c`` is the call when ``join_calls``); ``where``
    adds conditions starting with ``and``."""
    join = " join calls c on c.id = r.call_id" if join_calls else ""
    return (
        f"select distinct on (r.call_id, r.evaluator_id) {columns} from evaluator_runs r{join} "  # noqa: S608
        f"where r.superseded_at is null {where} order by r.call_id, r.evaluator_id, r.created_at desc"
    )


def eval_status_sql(where: str = "") -> str:
    """SQL with one ``(call_id, eval_status)`` row per call that has current runs; a call without
    any is ``not_evaluated``."""
    return (
        "select cur.call_id, case "  # noqa: S608
        "when bool_or(cur.status in ('pending', 'running')) then 'running' "
        "when bool_or(cur.status = 'completed' and cur.verdict = 'fail') then 'failed' "
        "when bool_or(cur.status = 'completed') then 'passed' "
        "when bool_and(cur.status = 'skipped') then 'not_evaluated' "
        f"else 'error' end as eval_status from ({current_runs_sql(where)}) cur group by cur.call_id"
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


async def current_by_call(session: AsyncSession, call_ids: Sequence[str]) -> dict[str, list[EvaluatorRun]]:
    """The current runs of each call (calls without runs are left out)."""
    runs: dict[str, list[EvaluatorRun]] = {}
    if call_ids:
        rows = await session.execute(select(EvaluatorRun).where(EvaluatorRun.call_id.in_(list(call_ids))))
        for row in rows.scalars():
            runs.setdefault(row.call_id, []).append(row)
    return {call_id: split_current(found)[0] for call_id, found in runs.items()}


async def call_statuses(session: AsyncSession, call_ids: Sequence[str]) -> dict[str, EvalStatus]:
    current = await current_by_call(session, call_ids)
    return {call_id: status_of(current.get(call_id, []))[0] for call_id in call_ids}


def missing_evaluators(current: Sequence[EvaluatorRun], enabled: dict[str, int]) -> list[str]:
    """Enabled evaluators (id to current version) without a completed or in-flight current run of
    that version."""
    have = {
        r.evaluator_id: r.evaluator_version
        for r in current
        if r.status in ("completed", "pending", "running")
    }
    return [e for e, version in enabled.items() if have.get(e) != version]


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
