"""Run comparison and scorecard inputs (008 T052, T063, T065; FR-019 to FR-021).

* ``verdict_rows``: each call's current 007 evaluator runs (newest unsuperseded run per
  evaluator) with their items, as scorecard ``VerdictRow`` values keyed as the caller asks.
* ``build_comparison``: original and simulated transcripts in the contract's item shape (tool
  outputs carry the answer source), the flow nodes visited on each side, the replay divergence
  turn with the caller turns never used, and a verdict table per evaluator. A verdict change is
  only shown between results of the same evaluator version.
* ``scorecard_for``: loads a batch's verdicts (against its base calls, or another batch over the
  same calls) and runs ``scorecard.compute_scorecard``.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.calls import transcript
from app.calls.lookups import config_for
from app.calls.models import Call
from app.core.errors import ProblemError, field_error, validation_failed
from app.evals.models import EvaluatorResultItem
from app.evals.views import current_runs_sql
from app.flows.compiled import compiled_view
from app.simulator.models import SimulationExperiment, SimulationRun
from app.simulator.scorecard import ExcludedRun, ItemVerdict, Scorecard, VerdictRow, compute_scorecard
from app.simulator.service import experiment_runs, get_experiment, snapshot_of
from app.testing import calls as sim_calls


async def current_runs(session: AsyncSession, call_ids: Sequence[str]) -> list[Any]:
    if not call_ids:
        return []
    sql = (
        "select cur.id, cur.call_id, cur.evaluator_id, cur.evaluator_version, cur.status, cur.verdict, "  # noqa: S608
        "cur.score, cur.rationale, e.name, e.display_name, e.scope from ("
        + current_runs_sql("and r.call_id = any(:ids)")
        + ") cur join evaluators e on e.id = cur.evaluator_id"
    )
    return list((await session.execute(text(sql), {"ids": list(call_ids)})).all())


async def verdict_rows(session: AsyncSession, keys: Mapping[str, str]) -> list[VerdictRow]:
    """``keys`` maps call id to the row key (the base call id the call belongs to)."""
    runs = await current_runs(session, list(keys))
    items: dict[str, list[ItemVerdict]] = {}
    run_ids = [r.id for r in runs if r.status == "completed"]
    if run_ids:
        rows = await session.execute(
            select(EvaluatorResultItem)
            .where(EvaluatorResultItem.run_id.in_(run_ids))
            .order_by(EvaluatorResultItem.run_id, EvaluatorResultItem.position)
        )
        for item in rows.scalars():
            items.setdefault(item.run_id, []).append(
                ItemVerdict(item.flow_node_id, item.flow_node_label, item.verdict, item.score)
            )
    return [
        VerdictRow(
            key=keys[r.call_id],
            evaluator_id=r.evaluator_id,
            evaluator_name=r.name,
            evaluator_display_name=r.display_name,
            evaluator_version=int(r.evaluator_version),
            scope=r.scope,
            status=r.status,
            verdict=r.verdict,
            score=float(r.score) if r.score is not None else None,
            items=tuple(items.get(r.id, ())),
        )
        for r in runs
    ]


def node_labels(config: Mapping[str, Any]) -> dict[str, str]:
    return compiled_view(config).labels()


def transcript_view(items: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in items:
        kind = item.get("type")
        if kind == "message" and str(item.get("text") or "").strip():
            out.append(
                {
                    "type": "message",
                    "role": "user" if item.get("role") == "user" else "assistant",
                    "content": str(item["text"]),
                    "node_id": item.get("node_id"),
                }
            )
        elif kind == "tool_call":
            args = item.get("arguments")
            out.append(
                {
                    "type": "function_call",
                    "name": str(item.get("name") or "tool"),
                    "arguments": args if isinstance(args, str) else json.dumps(args or {}, sort_keys=True),
                    "node_id": item.get("node_id"),
                }
            )
        elif kind == "tool_result":
            entry: dict[str, Any] = {
                "type": "function_call_output",
                "name": str(item.get("name") or "tool"),
                "output": str(item.get("output") or ""),
                "is_error": bool(item.get("is_error")),
            }
            if item.get("answer_source") in ("mock", "recorded", "synthesized", "error"):
                entry["answer_source"] = item["answer_source"]
            out.append(entry)
    return out


async def node_path(session: AsyncSession, call: Call, labels: Mapping[str, str]) -> list[dict[str, str]]:
    path = [t.to_node_id for t in await transcript.flow_transitions(session, call)]
    return [{"node_id": n, "node_label": labels.get(n, n)} for n in path]


async def side(session: AsyncSession, call: Call, labels: Mapping[str, str]) -> dict[str, Any]:
    return {
        "call_id": call.id,
        "transcript": transcript_view(transcript.items(call)),
        "node_path": await node_path(session, call, labels),
    }


def change_of(original: str | None, simulated: str | None, same_version: bool) -> str:
    if not same_version or original not in ("pass", "fail") or simulated not in ("pass", "fail"):
        return "not_comparable"
    if original == simulated:
        return "unchanged"
    return "improved" if simulated == "pass" else "regressed"


async def verdict_table(
    session: AsyncSession, original_id: str | None, simulated_id: str
) -> list[dict[str, Any]]:
    runs = await current_runs(session, [c for c in (original_id, simulated_id) if c])
    by_eval: dict[str, dict[str, Any]] = {}
    for r in runs:
        entry = by_eval.setdefault(r.evaluator_id, {"name": r.display_name, "scope": r.scope})
        entry["sim" if r.call_id == simulated_id else "orig"] = r
    out = []
    for evaluator_id, entry in by_eval.items():
        sim, orig = entry.get("sim"), entry.get("orig")
        either = sim if sim is not None else orig
        assert either is not None
        version = int(either.evaluator_version)

        def verdict(run: Any) -> str | None:
            if run is None:
                return None
            if run.status == "error":
                return "error"
            return str(run.verdict) if run.status == "completed" and run.verdict else None

        same = (
            sim is not None and orig is not None and int(sim.evaluator_version) == int(orig.evaluator_version)
        )
        out.append(
            {
                "evaluator_id": evaluator_id,
                "evaluator_display_name": entry["name"],
                "evaluator_version": version,
                "scope": entry["scope"],
                "node_id": None,
                "original": verdict(orig),
                "simulated": verdict(sim),
                "change": change_of(verdict(orig), verdict(sim), same),
                "original_score": float(orig.score) if orig is not None and orig.score is not None else None,
                "simulated_score": float(sim.score) if sim is not None and sim.score is not None else None,
                "simulated_reason": sim.rationale if sim is not None else None,
                "original_reason": orig.rationale if orig is not None else None,
            }
        )
    return sorted(out, key=lambda v: str(v["evaluator_display_name"]).casefold())


async def build_comparison(session: AsyncSession, run: SimulationRun) -> dict[str, Any]:
    if run.status != "completed" or run.output_call_id is None:
        raise ProblemError(
            409, "run_not_completed", "Run not finished", "The comparison is ready once the run completes."
        )
    config = await snapshot_of(session, run)
    labels = node_labels(config)
    simulated = await session.get(Call, run.output_call_id)
    assert simulated is not None
    base = await session.get(Call, run.base_call_id) if run.base_call_id else None
    unused: list[str] = []
    if run.mode == "replay" and base is not None:
        turns = sim_calls.replay_material(base).caller_turns
        used = sum(1 for m in transcript.read(simulated).messages if m.role == "user")
        unused = turns[used:]
    if base is not None:
        base_labels = {**node_labels(await config_for(session, base) or {}), **labels}
        original = await side(session, base, base_labels)
    else:
        original = None
    return {
        "simulation_run_id": run.id,
        "original": original,
        "simulated": await side(session, simulated, labels),
        "diverged_at_turn": run.diverged_at_turn,
        "unused_caller_turns": unused,
        "verdicts": await verdict_table(session, base.id if base is not None else None, simulated.id),
    }


def excluded(runs: Sequence[SimulationRun]) -> list[ExcludedRun]:
    return [ExcludedRun(r.id, r.status, r.error_message) for r in runs if r.status in ("failed", "cancelled")]


async def scorecard_for(
    session: AsyncSession,
    experiment_id: str,
    *,
    baseline: str = "original",
    baseline_experiment_id: str | None = None,
) -> tuple[SimulationExperiment, Scorecard]:
    exp = await get_experiment(session, experiment_id)
    runs = await experiment_runs(session, exp.id)
    keys = [r.base_call_id for r in runs if r.base_call_id]
    done = [r for r in runs if r.status == "completed" and r.output_call_id and r.base_call_id]
    sim_rows = await verdict_rows(session, {r.output_call_id: r.base_call_id for r in done})  # type: ignore[misc]
    if baseline == "experiment":
        if not baseline_experiment_id:
            raise validation_failed(
                [field_error("/baseline_experiment_id", "required", "Choose the batch to compare against")]
            )
        other = await get_experiment(session, baseline_experiment_id)
        other_runs = await experiment_runs(session, other.id)
        shared = {r.base_call_id for r in other_runs} & set(keys)
        if other.agent_id != exp.agent_id or not shared or other.id == exp.id:
            raise validation_failed(
                [
                    field_error(
                        "/baseline_experiment_id", "invalid_format", "Choose a batch over the same calls"
                    )
                ]
            )
        base_map = {
            r.output_call_id: r.base_call_id
            for r in other_runs
            if r.status == "completed" and r.output_call_id and r.base_call_id
        }
        base_rows = await verdict_rows(session, base_map)
    else:
        base_rows = await verdict_rows(session, {k: k for k in keys})
    card = compute_scorecard(
        keys=keys,
        base_rows=base_rows,
        sim_rows=sim_rows,
        excluded_runs=excluded(runs),
        sim_keys=[r.base_call_id for r in done if r.base_call_id],
        baseline="experiment" if baseline == "experiment" else "original",
    )
    return exp, card


def score_row(s: Any) -> dict[str, Any]:
    return {
        "evaluator_id": s.evaluator_id,
        "evaluator_name": s.evaluator_name,
        "evaluator_display_name": s.evaluator_display_name,
        "evaluator_version": s.evaluator_version,
        "scope": s.scope,
        "node_id": s.node_id,
        "node_label": s.node_label,
        "base_n": s.base_n,
        "base_passes": s.base_passes,
        "base_pass_rate": s.base_pass_rate,
        "sim_n": s.sim_n,
        "sim_passes": s.sim_passes,
        "sim_pass_rate": s.sim_pass_rate,
        "delta_pp": s.delta_pp,
        "base_mean_score": s.base_mean_score,
        "sim_mean_score": s.sim_mean_score,
        "pairs": {
            "n": s.pairs.n,
            "improved": s.pairs.improved,
            "regressed": s.pairs.regressed,
            "unchanged_pass": s.pairs.unchanged_pass,
            "unchanged_fail": s.pairs.unchanged_fail,
            "version_mismatch": s.pairs.version_mismatch,
        },
    }


def scorecard_view(experiment_id: str, card: Scorecard, baseline_experiment_id: str | None) -> dict[str, Any]:
    return {
        "experiment_id": experiment_id,
        "baseline": card.baseline,
        "baseline_experiment_id": baseline_experiment_id if card.baseline == "experiment" else None,
        "base_call_count": card.base_call_count,
        "sim_call_count": card.sim_call_count,
        "excluded_runs": [
            {"simulation_run_id": e.simulation_run_id, "status": e.status, "error_message": e.error_message}
            for e in card.excluded_runs
        ],
        "evaluators": [score_row(s) for s in card.evaluators],
        "by_node": [score_row(s) for s in card.by_node],
    }
