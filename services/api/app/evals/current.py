"""The one "current run" rule and the evaluation status it gives a call.

A call's *current* runs are its newest run per evaluator among the runs not yet superseded. Its
status derives from them: running while any is in flight, failed if any completed run failed,
passed if any completed, not evaluated when every run was skipped, otherwise error.
``current_runs_sql`` and ``eval_status_sql`` state the rule for SQL readers, ``split_current``,
``status_of`` and ``call_eval_status`` for loaded rows; ``tests/unit/evals/test_current.py``
checks both agree on all five statuses."""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.models import Agent
from app.core.config import Settings
from app.evals.models import EvaluatorRun
from app.evals.scoring import EvalStatus, RunState, run_counts
from app.evals.service import enabled_evaluators


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


def call_eval_status(runs: Sequence[RunState]) -> EvalStatus:
    """Over current runs: running if any is in flight, failed if any completed run failed, passed if
    any completed, not evaluated when every run was skipped, otherwise error."""
    if not runs:
        return "not_evaluated"
    if any(r.status in ("pending", "running") for r in runs):
        return "running"
    completed = [r for r in runs if r.status == "completed"]
    if any(r.verdict == "fail" for r in completed):
        return "failed"
    if completed:
        return "passed"
    if all(r.status == "skipped" for r in runs):
        return "not_evaluated"
    return "error"


async def missing_by_call(
    session: AsyncSession, agent: Agent, settings: Settings, call_ids: Sequence[str]
) -> dict[str, list[str]]:
    """Per call, the evaluators enabled for ``agent`` that have no completed or in-flight current
    run of their current version (every call is a key)."""
    enabled = {r.row.id: r.row.current_version for r in await enabled_evaluators(session, agent, settings)}
    current = await current_by_call(session, call_ids)
    return {call_id: missing_evaluators(current.get(call_id, []), enabled) for call_id in call_ids}
