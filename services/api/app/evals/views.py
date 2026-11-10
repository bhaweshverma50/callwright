"""Evaluator run views for the evals router (the current-run rule is ``evals.current``)."""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing.models import CreditTransaction
from app.evals.models import EvaluatorResultItem, EvaluatorRun
from app.evaluators.models import EvaluatorRow


def run_view(
    run: EvaluatorRun, row: EvaluatorRow | None, items: Sequence[EvaluatorResultItem], charged: Decimal | None
) -> dict[str, Any]:
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
    txn_ids = [r.charge_txn_id for r in runs if r.charge_txn_id]
    billed: dict[str, Decimal] = {}
    if txn_ids:
        billed = {
            t.id: -Decimal(t.amount_usd)
            for t in (
                await session.execute(select(CreditTransaction).where(CreditTransaction.id.in_(txn_ids)))
            ).scalars()
        }
    return [
        run_view(r, rows.get(r.evaluator_id), items.get(r.id, []), billed.get(r.charge_txn_id or ""))
        for r in runs
    ]


def ordered(views: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(views, key=lambda v: (str(v["evaluator_display_name"]).casefold(), v["created_at"]))
