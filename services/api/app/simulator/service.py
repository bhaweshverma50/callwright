"""Simulation runs and batches (008 T010, T051, T064, T071, T081; FR-011 to FR-024).

Run lifecycle (research R1, R11): the API inserts the run as ``pending`` and enqueues
``dispatch_simulation`` (``jobs.py``), which checks the balance, writes the persona brief when
one must be extracted, takes a semaphore slot and enqueues the text runner. The runner fetches
the spec (the run becomes ``running`` and its simulated call is created), streams the
conversation to ``/internal/calls/{id}/events`` and posts the result: the run is charged once
(``simulation.replay`` or ``simulation.persona``, plus ``simulation.tool_synth`` for generated
tool stand-ins), the base call is evaluated at the current evaluator versions when it lacks
results, and its batch's counters and status move on. The simulated call's post-call pipeline
(analysis and 007's evaluators) starts when its ``ended`` event arrives.

Interface for 009 (issue validation):

* ``start_experiment(session, settings, workspace_id=..., agent_id=..., mode=..., target=...,
  base_call_ids=..., source="issue_validation", issue_id=...)`` creates a batch; enqueue the
  returned run ids with ``jobs.DISPATCH_SIMULATION`` after commit (``enqueue_runs``).
* ``targets.canonical_hash(snapshot)`` compares configurations.
* ``on_experiment_finished(source, callback)`` registers ``async callback(workspace_id,
  experiment_id)``, fired once per batch when it reaches a final status.
* ``scorecard_for(session, experiment_id, ...)`` and ``scorecard.compute_scorecard`` /
  ``pair_verdicts`` read the result.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Mapping, Sequence
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.models import Agent
from app.billing import service as billing
from app.caller_language.options import language_options
from app.calls.models import Call, transition
from app.core.config import Settings
from app.core.errors import ProblemError, field_error, not_found, validation_failed
from app.core.ids import is_valid_id, new_id
from app.simulator import calls as sim_calls
from app.simulator.charges import charge_run, merge_usage
from app.simulator.models import SimulationExperiment, SimulationRun
from app.simulator.targets import agent_type_of, require_agent, resolve_target, runnable_problem

logger = logging.getLogger(__name__)

MIN_BATCH = 2
MAX_BATCH = 100
DEFAULT_TURNS = 20
MAX_TURNS = 50
ACTIVE = ("pending", "running")
FINAL = ("completed", "failed", "cancelled")
MODE_FEATURE = {"replay": "simulation.replay", "persona": "simulation.persona"}
ExperimentHook = Callable[[str, str], Awaitable[None]]
_hooks: dict[str, list[ExperimentHook]] = {}


def on_experiment_finished(source: str, callback: ExperimentHook) -> None:
    """Register ``async callback(workspace_id, experiment_id)`` for batches of ``source``."""
    _hooks.setdefault(source, []).append(callback)


def clear_hooks(source: str | None = None) -> None:
    if source is None:
        _hooks.clear()
    else:
        _hooks.pop(source, None)


async def fire_hooks(source: str, workspace_id: str, experiment_id: str) -> None:
    for callback in list(_hooks.get(source, [])):
        try:
            await callback(workspace_id, experiment_id)
        except Exception:
            logger.exception("experiment hook failed for %s", experiment_id)


def run_settings(raw: Mapping[str, Any] | None, settings: Settings) -> dict[str, Any]:
    raw = dict(raw or {})
    try:
        turns = int(raw.get("max_caller_turns") or DEFAULT_TURNS)
    except (TypeError, ValueError):
        turns = DEFAULT_TURNS
    policy = (
        raw.get("missing_mock_policy") if raw.get("missing_mock_policy") in ("synthesize", "error") else None
    )
    return {
        "max_caller_turns": max(1, min(MAX_TURNS, turns)),
        "missing_mock_policy": policy or "synthesize",
        "persona_model": str(raw.get("persona_model") or settings.simulator_model),
    }


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _money(value: Decimal | None) -> float | None:
    return float(value) if value is not None else None


def counts_view(raw: Mapping[str, Any] | None) -> dict[str, int]:
    raw = raw or {}
    return {k: int(raw.get(k) or 0) for k in ("mock", "recorded", "synthesized", "error")}


def run_view(
    run: SimulationRun, *, agent_name: str | None = None, eval_status: str = "not_started"
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "simulation_run_id": run.id,
        "agent_id": run.agent_id,
        "experiment_id": run.experiment_id,
        "base_call_id": run.base_call_id,
        "mode": run.mode,
        "target_type": run.target_type,
        "agent_version_id": run.agent_version_id,
        "variant_label": run.variant_label,
        "config_hash": run.config_hash,
        "persona_brief": run.persona_brief,
        "persona_source": run.persona_source,
        "status": run.status,
        "output_call_id": run.output_call_id,
        "end_reason": run.end_reason,
        "diverged_at_turn": run.diverged_at_turn,
        "answer_source_counts": counts_view(run.answer_source_counts),
        "eval_status": eval_status,
        "cost_usd": _money(run.cost_usd),
        "error_message": run.error_message,
        "created_at": run.created_at.isoformat(),
        "started_at": _iso(run.started_at),
        "finished_at": _iso(run.finished_at),
    }
    if agent_name is not None:
        out["agent_name"] = agent_name
    return out


def experiment_view(exp: SimulationExperiment, *, agent_name: str | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {
        "experiment_id": exp.id,
        "agent_id": exp.agent_id,
        "name": exp.name,
        "mode": exp.mode,
        "target_type": exp.target_type,
        "agent_version_id": exp.agent_version_id,
        "variant_label": exp.variant_label,
        "variant_diff": exp.variant_diff,
        "config_hash": exp.config_hash,
        "source": exp.source,
        "dataset_id": exp.dataset_id,
        "issue_id": exp.issue_id,
        "settings": dict(exp.settings or {}),
        "status": exp.status,
        "total_count": exp.total_count,
        "completed_count": exp.completed_count,
        "failed_count": exp.failed_count,
        "cancelled_count": exp.cancelled_count,
        "cost_usd": _money(exp.cost_usd),
        "error_message": exp.error_message,
        "created_at": exp.created_at.isoformat(),
        "finished_at": _iso(exp.finished_at),
    }
    if agent_name is not None:
        out["agent_name"] = agent_name
    return out


async def agent_names(session: AsyncSession, agent_ids: Sequence[str]) -> dict[str, str]:
    ids = list(dict.fromkeys(agent_ids))
    if not ids:
        return {}
    rows = await session.execute(select(Agent.id, Agent.name).where(Agent.id.in_(ids)))
    return {i: n for i, n in rows.all()}


async def eval_statuses(session: AsyncSession, runs: Sequence[SimulationRun]) -> dict[str, str]:
    """Evaluation progress of each run's simulated call (007 run states)."""
    from app.evals.models import EvaluatorRun
    from app.evals.views import split_current, status_of

    call_ids = [r.output_call_id for r in runs if r.output_call_id and r.status == "completed"]
    out = {r.id: "not_started" for r in runs}
    if not call_ids:
        return out
    pipeline = dict(
        (await session.execute(select(Call.id, Call.pipeline_status).where(Call.id.in_(call_ids)))).all()
    )
    evals: dict[str, list[EvaluatorRun]] = {}
    for row in (
        await session.execute(select(EvaluatorRun).where(EvaluatorRun.call_id.in_(call_ids)))
    ).scalars():
        evals.setdefault(row.call_id, []).append(row)
    for run in runs:
        if run.output_call_id not in pipeline:
            continue
        current, _ = split_current(evals.get(run.output_call_id, []))
        if not current:
            out[run.id] = (
                "pending" if pipeline[run.output_call_id] in ("not_started", "running") else "not_started"
            )
            continue
        status, _, _ = status_of(current)
        out[run.id] = {
            "running": "running",
            "passed": "completed",
            "failed": "completed",
            "error": "failed",
        }.get(status, "not_started")
    return out


async def views(session: AsyncSession, runs: Sequence[SimulationRun]) -> list[dict[str, Any]]:
    names = await agent_names(session, [r.agent_id for r in runs])
    statuses = await eval_statuses(session, runs)
    return [run_view(r, agent_name=names.get(r.agent_id), eval_status=statuses[r.id]) for r in runs]


# Base calls -----------------------------------------------------------------------------------


def invalid_calls_problem(
    invalid: Sequence[tuple[int, str, str]], pointer: str = "/base_call_ids"
) -> ProblemError:
    errors = [
        field_error(f"{pointer}/{i}", reason, sim_calls.REASON_TEXT[reason]) for i, _, reason in invalid
    ]
    return ProblemError(
        422,
        "invalid_calls",
        "Some calls cannot be simulated",
        "Remove the calls listed below and try again.",
        errors=errors,
        extra={"invalid_calls": [{"call_id": c, "reason": r} for _, c, r in invalid]},
    )


def mixed_agents_problem() -> ProblemError:
    return ProblemError(
        422,
        "mixed_agents",
        "Calls from several agents",
        "These calls belong to more than one agent. Narrow the selection to one agent.",
    )


async def check_base_calls(session: AsyncSession, agent_id: str, call_ids: Sequence[str]) -> list[Call]:
    calls = await sim_calls.load_calls(session, call_ids)
    agents = {c.agent_id for c in calls.values()}
    if len(agents) > 1 or (agents and agent_id not in agents):
        raise mixed_agents_problem()
    invalid = []
    for i, call_id in enumerate(call_ids):
        reason = sim_calls.call_problem(calls.get(call_id), agent_id)
        if reason:
            invalid.append((i, call_id, reason))
    if invalid:
        raise invalid_calls_problem(invalid)
    return [calls[c] for c in call_ids]


# Individual runs ------------------------------------------------------------------------------


async def start_run(
    session: AsyncSession,
    settings: Settings,
    *,
    workspace_id: str,
    user_id: str | None,
    body: Mapping[str, Any],
) -> SimulationRun:
    agent = await require_agent(session, str(body["agent_id"]), pointer="/agent_id")
    mode = str(body["mode"])
    base_id = body.get("base_call_id")
    brief = body.get("persona_brief")
    if mode == "replay" and not base_id:
        raise validation_failed([field_error("/base_call_id", "required", "Choose a call to replay")])
    if mode == "persona" and not base_id and not brief:
        raise validation_failed(
            [
                field_error(
                    "/persona_brief", "required", "Write a persona brief or choose a call to start from"
                )
            ]
        )
    base = None
    if base_id:
        [base] = await check_base_calls(session, agent.id, [str(base_id)])
    target = await resolve_target(session, agent, body.get("target"), default="published")
    problem = runnable_problem(agent_type_of(agent), target.config)
    if problem is not None:
        raise problem
    if await billing.get_balance(session, workspace_id) <= 0:
        raise billing.insufficient_credit("Add funds to run simulations.")
    run = SimulationRun(
        id=new_id("srun"),
        workspace_id=workspace_id,
        agent_id=agent.id,
        experiment_id=None,
        base_call_id=base.id if base is not None else None,
        mode=mode,
        target_type=target.target_type,
        agent_version_id=target.agent_version_id,
        variant_label=target.variant_label,
        config_snapshot=target.config,
        config_hash=target.config_hash,
        persona_brief=dict(brief) if brief else None,
        persona_source="provided" if brief else None,
        dynamic_variables=sim_calls.run_variables(target.config, base, body.get("dynamic_variables")),
        settings=run_settings(body.get("settings"), settings),
        status="pending",
        answer_source_counts={},
        usage={},
        created_by=user_id,
        created_at=datetime.now(UTC),
    )
    session.add(run)
    await session.flush()
    return run


async def get_run(session: AsyncSession, run_id: str, *, lock: bool = False) -> SimulationRun:
    if not is_valid_id(run_id, "srun"):
        raise not_found("simulation run")
    query = select(SimulationRun).where(SimulationRun.id == run_id)
    if lock:
        query = query.with_for_update()
    run = (await session.execute(query)).scalar_one_or_none()
    if run is None:
        raise not_found("simulation run")
    return run


async def snapshot_of(session: AsyncSession, run: SimulationRun) -> dict[str, Any]:
    if run.config_snapshot is not None:
        return dict(run.config_snapshot)
    exp = await session.get(SimulationExperiment, run.experiment_id)
    return dict(exp.config_snapshot) if exp is not None else {}


async def list_runs(
    session: AsyncSession,
    *,
    agent_id: str | None,
    base_call_id: str | None,
    experiment_id: str | None,
    standalone: bool | None,
    status: str | None,
    page: int,
    page_size: int,
) -> tuple[list[SimulationRun], int]:
    where = []
    if agent_id:
        where.append(SimulationRun.agent_id == agent_id)
    if base_call_id:
        where.append(SimulationRun.base_call_id == base_call_id)
    if experiment_id:
        where.append(SimulationRun.experiment_id == experiment_id)
    if standalone is True:
        where.append(SimulationRun.experiment_id.is_(None))
    elif standalone is False:
        where.append(SimulationRun.experiment_id.is_not(None))
    if status:
        where.append(SimulationRun.status == status)
    total = int(
        (await session.execute(select(func.count()).select_from(SimulationRun).where(*where))).scalar_one()
    )
    rows = await session.execute(
        select(SimulationRun)
        .where(*where)
        .order_by(SimulationRun.created_at.desc(), SimulationRun.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return list(rows.scalars()), total


async def cancel_run(session: AsyncSession, run_id: str) -> SimulationRun:
    run = await get_run(session, run_id, lock=True)
    if run.status != "pending":
        raise ProblemError(
            409, "run_not_pending", "Run already started", "Only runs that have not started can be cancelled."
        )
    run.status = "cancelled"
    run.finished_at = datetime.now(UTC)
    await session.flush()
    if run.experiment_id:
        await refresh_experiment(session, run.experiment_id)
    return run


async def fail_run(session: AsyncSession, run: SimulationRun, message: str) -> None:
    """Infrastructure failure (no credit, runner lost): never charged as a simulation."""
    if run.status in FINAL:
        return
    run.status = "failed"
    run.end_reason = run.end_reason or "error"
    run.error_message = message[:2000]
    run.finished_at = datetime.now(UTC)
    await close_output_call(session, run)
    await session.flush()
    if run.experiment_id:
        await refresh_experiment(session, run.experiment_id)


async def close_output_call(session: AsyncSession, run: SimulationRun) -> None:
    if run.output_call_id is None:
        return
    call = await session.get(Call, run.output_call_id)
    if call is None:
        return
    now = datetime.now(UTC)
    if call.status == "queued":
        await transition(
            session,
            call.id,
            "queued",
            "failed",
            ended_at=now,
            disconnect_reason="error",
            diagnostic="simulation_failed",
            billable_seconds=0,
        )
    elif call.status == "in_progress":
        await transition(
            session,
            call.id,
            "in_progress",
            "ended",
            ended_at=now,
            disconnect_reason="error",
            diagnostic="simulation_failed",
            billable_seconds=0,
        )


# Batches ----------------------------------------------------------------------------------------


def default_name(now: datetime) -> str:
    return f"Simulation {now.strftime('%Y-%m-%d %H:%M')}"


async def dataset_calls(session: AsyncSession, dataset_id: str, agent_id: str) -> tuple[list[str], int]:
    """Available calls of a dataset (newest first) and the number of unavailable ones skipped."""
    from app.datasets.models import Dataset, DatasetItem

    dataset = await session.get(Dataset, dataset_id) if is_valid_id(dataset_id, "ds") else None
    if dataset is None:
        raise validation_failed(
            [field_error("/dataset_id", "invalid_format", "Choose a dataset of this workspace")]
        )
    if dataset.agent_id != agent_id:
        raise validation_failed(
            [field_error("/dataset_id", "invalid_format", "The dataset belongs to another agent")]
        )
    rows = await session.execute(
        select(DatasetItem.call_id)
        .where(DatasetItem.dataset_id == dataset_id)
        .order_by(DatasetItem.added_at.desc())
    )
    ids = [r for r in rows.scalars()]
    calls = await sim_calls.load_calls(session, ids)
    usable = [c for c in ids if sim_calls.call_problem(calls.get(c), agent_id) is None]
    return usable, len(ids) - len(usable)


async def start_experiment(
    session: AsyncSession,
    settings: Settings,
    *,
    workspace_id: str,
    agent_id: str,
    mode: str,
    target: Mapping[str, Any] | None = None,
    base_call_ids: Sequence[str] | None = None,
    dataset_id: str | None = None,
    run_settings_raw: Mapping[str, Any] | None = None,
    name: str | None = None,
    source: str | None = None,
    issue_id: str | None = None,
    user_id: str | None = None,
) -> tuple[SimulationExperiment, list[str]]:
    """Create a batch and its pending runs. Returns (batch, run ids to dispatch after commit)."""
    if (base_call_ids is None) == (dataset_id is None):
        raise validation_failed(
            [field_error("", "invalid_format", "Give either base_call_ids or dataset_id")]
        )
    agent = await require_agent(session, agent_id, pointer="/agent_id")
    if dataset_id is not None:
        ids, _skipped = await dataset_calls(session, dataset_id, agent.id)
        source = source or "dataset"
        if len(ids) > MAX_BATCH:
            raise validation_failed(
                [
                    field_error(
                        "/dataset_id",
                        "out_of_range",
                        f"A batch takes at most {MAX_BATCH} calls; this dataset has {len(ids)}",
                    )
                ]
            )
    else:
        ids = list(dict.fromkeys(base_call_ids or []))
        source = source or "call_selection"
    if len(ids) < MIN_BATCH or len(ids) > MAX_BATCH:
        pointer = "/dataset_id" if dataset_id else "/base_call_ids"
        raise validation_failed(
            [
                field_error(
                    pointer,
                    "out_of_range",
                    f"A batch needs {MIN_BATCH} to {MAX_BATCH} calls; this has {len(ids)}",
                )
            ]
        )
    bases = await check_base_calls(session, agent.id, ids)
    resolved = await resolve_target(session, agent, target, default="published")
    problem = runnable_problem(agent_type_of(agent), resolved.config)
    if problem is not None:
        raise problem
    if await billing.get_balance(session, workspace_id) <= 0:
        raise billing.insufficient_credit("Add funds to run simulations.")
    now = datetime.now(UTC)
    values = run_settings(run_settings_raw, settings)
    exp = SimulationExperiment(
        id=new_id("exp"),
        workspace_id=workspace_id,
        agent_id=agent.id,
        name=(name or "").strip()[:120] or default_name(now),
        mode=mode,
        target_type=resolved.target_type,
        agent_version_id=resolved.agent_version_id,
        variant_label=resolved.variant_label,
        config_snapshot=resolved.config,
        config_hash=resolved.config_hash,
        variant_diff=resolved.variant_diff,
        source=source,
        dataset_id=dataset_id,
        issue_id=issue_id,
        settings=values,
        status="pending",
        total_count=len(bases),
        created_by=user_id,
        created_at=now,
    )
    session.add(exp)
    await session.flush()
    run_ids = []
    for base in bases:
        run = SimulationRun(
            id=new_id("srun"),
            workspace_id=workspace_id,
            agent_id=agent.id,
            experiment_id=exp.id,
            base_call_id=base.id,
            mode=mode,
            target_type=resolved.target_type,
            agent_version_id=resolved.agent_version_id,
            variant_label=resolved.variant_label,
            config_snapshot=None,
            config_hash=resolved.config_hash,
            dynamic_variables=sim_calls.run_variables(resolved.config, base, None),
            settings=values,
            status="pending",
            answer_source_counts={},
            usage={},
            created_by=user_id,
            created_at=now,
        )
        session.add(run)
        run_ids.append(run.id)
    await session.flush()
    return exp, run_ids


async def get_experiment(
    session: AsyncSession, experiment_id: str, *, lock: bool = False
) -> SimulationExperiment:
    if not is_valid_id(experiment_id, "exp"):
        raise not_found("simulation batch")
    query = select(SimulationExperiment).where(SimulationExperiment.id == experiment_id)
    if lock:
        query = query.with_for_update()
    exp = (await session.execute(query)).scalar_one_or_none()
    if exp is None:
        raise not_found("simulation batch")
    return exp


async def list_experiments(
    session: AsyncSession, *, agent_id: str | None, source: str | None, page: int, page_size: int
) -> tuple[list[SimulationExperiment], int]:
    where = []
    if agent_id:
        where.append(SimulationExperiment.agent_id == agent_id)
    if source:
        where.append(SimulationExperiment.source == source)
    total = int(
        (
            await session.execute(select(func.count()).select_from(SimulationExperiment).where(*where))
        ).scalar_one()
    )
    rows = await session.execute(
        select(SimulationExperiment)
        .where(*where)
        .order_by(SimulationExperiment.created_at.desc(), SimulationExperiment.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return list(rows.scalars()), total


def derived_status(statuses: Sequence[str]) -> str:
    """Batch status from its runs (data-model)."""
    if any(s in ACTIVE for s in statuses):
        return "running" if any(s != "pending" for s in statuses) else "pending"
    if any(s == "cancelled" for s in statuses):
        return "cancelled"
    if any(s == "completed" for s in statuses):
        return "completed"
    return "failed"


async def refresh_experiment(session: AsyncSession, experiment_id: str) -> SimulationExperiment | None:
    """Recompute a batch's counters, cost and status. Marks hooks due once it is final."""
    exp = await session.get(SimulationExperiment, experiment_id, with_for_update=True)
    if exp is None:
        return None
    rows = (
        await session.execute(
            select(SimulationRun.status, SimulationRun.cost_usd).where(
                SimulationRun.experiment_id == experiment_id
            )
        )
    ).all()
    statuses = [s for s, _ in rows]
    exp.completed_count = statuses.count("completed")
    exp.failed_count = statuses.count("failed")
    exp.cancelled_count = statuses.count("cancelled")
    exp.cost_usd = sum((c for _, c in rows if c is not None), Decimal(0))
    exp.status = derived_status(statuses)
    if exp.status in FINAL and exp.finished_at is None:
        exp.finished_at = datetime.now(UTC)
    await session.flush()
    return exp


async def cancel_experiment(
    session: AsyncSession, experiment_id: str
) -> tuple[SimulationExperiment, list[str]]:
    """Pending runs are cancelled (never charged); runs in progress finish. Returns the batch and
    the cancelled run ids that may hold a runner slot."""
    exp = await get_experiment(session, experiment_id, lock=True)
    rows = list(
        (
            await session.execute(
                select(SimulationRun)
                .where(SimulationRun.experiment_id == experiment_id, SimulationRun.status == "pending")
                .with_for_update()
            )
        ).scalars()
    )
    now = datetime.now(UTC)
    for run in rows:
        run.status = "cancelled"
        run.finished_at = now
    await session.flush()
    await refresh_experiment(session, experiment_id)
    return exp, [r.id for r in rows if r.dispatched_at is not None]


async def experiment_runs(session: AsyncSession, experiment_id: str) -> list[SimulationRun]:
    rows = await session.execute(
        select(SimulationRun)
        .where(SimulationRun.experiment_id == experiment_id)
        .order_by(SimulationRun.created_at, SimulationRun.id)
    )
    return list(rows.scalars())


async def claim_finished_hooks(session: AsyncSession, experiment_id: str) -> SimulationExperiment | None:
    """The batch when it is final and its hooks have not fired yet (marks them fired)."""
    result = await session.execute(
        update(SimulationExperiment)
        .where(
            SimulationExperiment.id == experiment_id,
            SimulationExperiment.status.in_(FINAL),
            SimulationExperiment.hooks_fired_at.is_(None),
        )
        .values(hooks_fired_at=datetime.now(UTC))
        .returning(SimulationExperiment.id)
    )
    if result.first() is None:
        return None
    return await session.get(SimulationExperiment, experiment_id)


# Runner side -------------------------------------------------------------------------------------


async def spec_for(session: AsyncSession, run_id: str) -> dict[str, Any]:
    """The runner's spec. Marks the run running and creates its simulated call."""
    run = await get_run(session, run_id, lock=True)
    if run.status not in ACTIVE or (run.status == "running" and run.output_call_id is None):
        raise ProblemError(409, "run_closed", "Run closed", "This simulation no longer needs a run.")
    config = await snapshot_of(session, run)
    base = await session.get(Call, run.base_call_id) if run.base_call_id else None
    now = datetime.now(UTC)
    if run.output_call_id is None:
        call = sim_calls.create_output_call(
            session,
            workspace_id=run.workspace_id,
            agent_id=run.agent_id,
            agent_version_id=run.agent_version_id,
            simulation_run_id=run.id,
            base=base,
            variables=run.dynamic_variables or {},
            now=now,
        )
        run.output_call_id = call.id
        run.status = "running"
        run.started_at = now
        await session.flush()
        if run.experiment_id:
            await refresh_experiment(session, run.experiment_id)
        channel = call.channel
    else:
        existing = await session.get(Call, run.output_call_id)
        channel = existing.channel if existing is not None else "web"
    spec: dict[str, Any] = {
        "workspace_id": run.workspace_id,
        "simulation_run_id": run.id,
        "output_call_id": run.output_call_id,
        "agent_id": run.agent_id,
        "agent_type": "flow" if config.get("type") == "flow" else "single_prompt",
        "channel": channel,
        "mode": run.mode,
        "config_snapshot": config,
        "settings": dict(run.settings or {}),
        "dynamic_variables": {str(k): str(v) for k, v in (run.dynamic_variables or {}).items()},
        "start_speaker": "user" if config.get("start_speaker") == "user" else "agent",
        "language_options": language_options(config),
    }
    if base is not None:
        material = sim_calls.replay_material(sim_calls.items_of(base))
        spec["original_node_path"] = material.node_path
        if run.mode == "replay":
            spec["start_speaker"] = material.start_speaker
            spec["caller_turns"] = material.caller_turns
            spec["recorded_tool_outputs"] = material.recorded_tool_outputs
    if run.persona_brief:
        spec["persona_brief"] = run.persona_brief
    return spec


async def record_result(session: AsyncSession, run_id: str, body: Mapping[str, Any]) -> SimulationRun | None:
    """Store the runner's result and charge a completed run once. Returns the run when it
    changed (None when the result was a duplicate or arrived for a closed run)."""
    run = await get_run(session, run_id, lock=True)
    if run.status != "running":
        return None
    if run.output_call_id:
        # Lock order: call row before the workspace billing lock. This transaction updates the run
        # twice (the charge flushes midway), so Postgres re-checks the deferred output_call_id
        # foreign key at commit, which needs a key-share lock on the simulated call. The call's
        # post-call pipeline holds that row FOR UPDATE and then takes the billing lock to charge
        # the analysis; taking the key-share here first makes us wait for it instead of deadlocking.
        await session.execute(
            select(Call.id).where(Call.id == run.output_call_id).with_for_update(key_share=True)
        )
    now = datetime.now(UTC)
    usage = merge_usage(body.get("usage") or {})
    run.usage = merge_usage(run.usage or {}, usage)
    run.answer_source_counts = counts_view(body.get("answer_source_counts"))
    run.diverged_at_turn = body.get("diverged_at_turn")
    run.end_reason = body.get("end_reason") or ("error" if body.get("status") == "failed" else None)
    if body.get("persona_brief") and not run.persona_brief:
        run.persona_brief = dict(body["persona_brief"])
        run.persona_source = "extracted"
    run.finished_at = now
    if body.get("status") != "completed":
        run.status = "failed"
        run.error_message = str(body.get("error_message") or "The simulation failed.")[:2000]
        await close_output_call(session, run)
    else:
        try:
            main = await charge_run(
                session,
                workspace_id=run.workspace_id,
                run_id=run.id,
                feature_key=MODE_FEATURE[run.mode],
                usage=usage,
                roles=("agent", "caller"),
                ref_type="simulation_run",
                ref_id=run.id,
            )
            total = main.billable_usd
            if (usage.get("synth") or {}).get("input_tokens") or (usage.get("synth") or {}).get(
                "output_tokens"
            ):
                synth = await charge_run(
                    session,
                    workspace_id=run.workspace_id,
                    run_id=run.id,
                    feature_key="simulation.tool_synth",
                    usage=usage,
                    roles=("synth",),
                    part="tool_synth",
                    ref_type="simulation_run",
                    ref_id=run.id,
                )
                total += synth.billable_usd
            run.cost_usd = (run.cost_usd or Decimal(0)) + total
            run.status = "completed"
        except ProblemError as exc:
            if exc.code != "insufficient_credit":
                raise
            run.status = "failed"
            run.error_message = "insufficient credit"
    await session.flush()
    if run.experiment_id:
        await refresh_experiment(session, run.experiment_id)
    return run


async def ensure_base_evaluation(session: AsyncSession, run: SimulationRun) -> str | None:
    """Evaluate the base call with the current evaluator versions when it lacks such results
    (research R7). Returns the run group id to execute after commit, or None."""
    if run.base_call_id is None or run.status != "completed":
        return None
    from app.evals.jobs import start_evaluation
    from app.evals.models import EvaluatorRun
    from app.evals.runner import AlreadyRunning
    from app.evals.service import resolve_all
    from app.evals.views import split_current

    base = await session.get(Call, run.base_call_id)
    agent = await session.get(Agent, run.agent_id)
    if base is None or agent is None:
        return None
    from app.evals.runtime import runtime

    resolved = await resolve_all(session, agent, runtime().settings.judge_models)
    enabled = {r.row.id: r.row.current_version for r in resolved if r.enabled}
    existing = list(
        (await session.execute(select(EvaluatorRun).where(EvaluatorRun.call_id == base.id))).scalars()
    )
    current, _ = split_current(existing)
    have = {
        r.evaluator_id: r.evaluator_version
        for r in current
        if r.status in ("completed", "pending", "running")
    }
    missing = [e for e, version in enabled.items() if have.get(e) != version]
    if not missing:
        return None
    try:
        start = await start_evaluation(
            session, base, trigger="simulation", idempotency_key=f"sim:{run.id}", evaluator_ids=missing
        )
    except (AlreadyRunning, ProblemError):
        return None
    return start.group.run_group_id if start.created and start.group.status == "active" else None


async def run_snapshot(session: AsyncSession, run_id: str) -> dict[str, Any] | None:
    """The exact configuration a simulation run used (007 judges simulated calls with it)."""
    run = await session.get(SimulationRun, run_id) if is_valid_id(run_id, "srun") else None
    return await snapshot_of(session, run) if run is not None else None
