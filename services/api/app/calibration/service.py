"""Calibration pairs and rows (007 T052; FR-026 to FR-031, research R7).

Pairs are (current completed pass or fail verdict, resolved human label) on live calls that
ended within the lookback window, optionally for one agent. ``version_scope=current`` keeps
only runs of each evaluator's current version. Evaluators whose items name a flow node also get
one row per node from the item verdicts. Threshold evaluators (a 0 to 1 ``threshold`` setting)
report agreement at the current threshold and the best threshold over the stored scores.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.calibration import math
from app.evals.models import AgentEvalSetting
from app.evals.settings import effective
from app.evaluators.models import EvaluatorRow

_CURRENT = """
select distinct on (r.call_id, r.evaluator_id) r.id, r.call_id, r.evaluator_id, r.evaluator_version,
       r.status, r.verdict, r.score
  from evaluator_runs r
  join calls c on c.id = r.call_id
 where r.superseded_at is null and c.origin = 'live' and c.ended_at >= :since {agent}
 order by r.call_id, r.evaluator_id, r.created_at desc
"""


def _scope(agent_id: str | None, lookback_days: int, now: datetime | None) -> tuple[str, dict[str, Any]]:
    params: dict[str, Any] = {"since": (now or datetime.now(UTC)) - timedelta(days=lookback_days)}
    agent = ""
    if agent_id:
        agent, params["agent"] = "and c.agent_id = :agent", agent_id
    return agent, params


async def resolved_labels(session: AsyncSession, agent: str, params: dict[str, Any]) -> dict[str, str]:
    rows = (
        await session.execute(
            text(
                "select n.call_id, n.label from annotations n join calls c on c.id = n.call_id "  # noqa: S608
                f"where c.origin = 'live' and c.ended_at >= :since {agent}"
            ),
            params,
        )
    ).all()
    by_call: dict[str, list[str]] = defaultdict(list)
    for call_id, label in rows:
        by_call[call_id].append(label)
    return {call_id: math.resolve_label(labels) for call_id, labels in by_call.items()}


def _threshold_field(row: EvaluatorRow) -> dict[str, Any] | None:
    for f in (row.settings_schema or {}).get("fields") or []:
        if f.get("key") == "threshold" and f.get("min") == 0 and f.get("max") == 1:
            return dict(f)
    return None


async def _current_threshold(session: AsyncSession, row: EvaluatorRow, agent_id: str | None) -> float:
    field = _threshold_field(row)
    assert field is not None
    if agent_id:
        setting = await session.get(AgentEvalSetting, (agent_id, row.id))
        values, _ = effective(row.settings_schema or {}, setting.overrides if setting else None)
        return float(values["threshold"])
    return float(field["default"])


def _row(
    ev: EvaluatorRow,
    pairs: Sequence[tuple[str, str]],
    scope: str,
    min_sample: int,
    *,
    node: tuple[str, str | None] | None = None,
) -> dict[str, Any]:
    m = math.matrix(pairs)
    a = math.agreement(m)
    ci = math.wilson_interval(m.agreements, m.n)
    return {
        "evaluator_id": ev.id,
        "evaluator_name": ev.name,
        "display_name": ev.display_name,
        "scope": ev.scope,
        "cost_class": ev.cost_class,
        "evaluator_version": ev.current_version if scope == "current" else None,
        "version_scope": scope,
        "flow_node_id": node[0] if node else None,
        "flow_node_label": node[1] if node else None,
        "both_pass": m.both_pass,
        "both_fail": m.both_fail,
        "over_eager": m.over_eager,
        "missed": m.missed,
        "n": m.n,
        "agreement_rate": round(a, 6) if a is not None else None,
        "agreement_ci": {"low": round(ci[0], 6), "high": round(ci[1], 6)} if ci else None,
        "under_min_sample": m.n < min_sample,
        "reading": math.reading(m, min_sample),
        "current_threshold": None,
        "best_threshold": None,
        "best_threshold_agreement": None,
    }


async def rows(
    session: AsyncSession,
    *,
    agent_id: str | None,
    lookback_days: int,
    version_scope: Literal["current", "all"],
    min_sample: int,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    agent, params = _scope(agent_id, lookback_days, now)
    labels = await resolved_labels(session, agent, params)
    usable = {c: label for c, label in labels.items() if label in ("good", "bad")}
    if not usable:
        return []
    runs = (await session.execute(text(_CURRENT.format(agent=agent)), params)).mappings().all()
    evaluators = {e.id: e for e in (await session.execute(select(EvaluatorRow))).scalars()}
    pairs: dict[str, list[tuple[str, str]]] = defaultdict(list)
    scored: dict[str, list[tuple[float, str]]] = defaultdict(list)
    run_ids: list[str] = []
    run_label: dict[str, tuple[str, str]] = {}
    for r in runs:
        ev = evaluators.get(r["evaluator_id"])
        label = usable.get(r["call_id"])
        if ev is None or label is None or r["status"] != "completed" or r["verdict"] not in ("pass", "fail"):
            continue
        if version_scope == "current" and r["evaluator_version"] != ev.current_version:
            continue
        pairs[ev.id].append((r["verdict"], label))
        if r["score"] is not None:
            scored[ev.id].append((float(r["score"]), label))
        run_ids.append(r["id"])
        run_label[r["id"]] = (ev.id, label)
    node_pairs: dict[tuple[str, str], list[tuple[str, str]]] = defaultdict(list)
    node_labels: dict[tuple[str, str], str | None] = {}
    if run_ids:
        items = (
            await session.execute(
                text(
                    "select run_id, flow_node_id, flow_node_label, verdict from evaluator_result_items "
                    "where run_id = any(:ids) and flow_node_id is not null and verdict in ('pass', 'fail')"
                ),
                {"ids": run_ids},
            )
        ).all()
        for run_id, node_id, node_label, verdict in items:
            evaluator_id, label = run_label[run_id]
            node_pairs[(evaluator_id, node_id)].append((verdict, label))
            node_labels[(evaluator_id, node_id)] = node_label
    out = []
    for evaluator_id, ev_pairs in pairs.items():
        ev = evaluators[evaluator_id]
        row = _row(ev, ev_pairs, version_scope, min_sample)
        if _threshold_field(ev) is not None:
            current = await _current_threshold(session, ev, agent_id)
            direction: math.Direction = "above_fails" if ev.output_kind == "anomaly" else "below_fails"
            row["current_threshold"] = current
            if row["n"] >= min_sample:
                at_current = math.agreement_at(scored[evaluator_id], current, direction)
                best = math.best_threshold(
                    scored[evaluator_id], current=current, direction=direction, min_sample=min_sample
                )
                if best is not None:
                    row["best_threshold"], row["best_threshold_agreement"] = best
                if at_current is not None:
                    row["agreement_at_current_threshold"] = round(at_current, 6)
        out.append(row)
        for (node_ev, node_id), p in sorted(node_pairs.items()):
            if node_ev == evaluator_id:
                out.append(
                    _row(
                        ev, p, version_scope, min_sample, node=(node_id, node_labels.get((node_ev, node_id)))
                    )
                )
    return sorted(out, key=lambda r: (r["display_name"].casefold(), r["flow_node_label"] or ""))


async def summary(
    session: AsyncSession,
    *,
    agent_id: str | None,
    lookback_days: int,
    min_sample: int,
    now: datetime | None = None,
) -> dict[str, int]:
    agent, params = _scope(agent_id, lookback_days, now)
    labels = await resolved_labels(session, agent, params)
    evaluated = set(
        (
            await session.execute(
                text(
                    "select cur.call_id from (" + _CURRENT.format(agent=agent) + ") cur "  # noqa: S608
                    "where cur.status = 'completed' and cur.verdict in ('pass', 'fail')"
                ),
                params,
            )
        ).scalars()
    )
    resolved = {c for c, label in labels.items() if label in ("good", "bad")}
    return {
        "annotated_calls": len(labels),
        "annotated_and_evaluated_calls": len(resolved & evaluated),
        "conflicting_label_calls": sum(1 for label in labels.values() if label == "conflict"),
        "min_sample_for_signal": min_sample,
    }
