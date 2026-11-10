"""Simulation jobs (008 T013, T051, T087) on the API's own arq queue.

* ``dispatch_simulation(workspace_id, simulation_run_id)``: a pending run is failed with
  "insufficient credit" at or below zero balance; a persona run from a base call gets its brief
  written first (``simulation.persona_extraction``); then the run takes a slot of the workspace
  semaphore (``dispatch.py``) and ``run_simulation`` goes to the text runner. Without a free slot
  the job re-enqueues itself after 5 s.
* ``after_result(...)``: what follows a runner result once its transaction committed: release
  the slot, evaluate the base call when needed, fire the batch's completion hooks once.
* ``sweep_simulations`` (cron, every minute): runs whose runner went silent for longer than
  ``dispatch.STALE_RUN_S`` fail ("the simulation runner stopped answering") and release their
  slots;
  batches whose last run ended fire their hooks.
* ``purge_simulation_data`` (cron, daily): retention (research R13). Simulated calls follow their
  base call: when the base call's transcript is gone, the persona brief and the simulated
  transcript are cleared too. Dataset items of purged calls read as unavailable (see datasets).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from callwright_contract.textsim import RUN_SIMULATION
from sqlalchemy import text

from app.billing import service as billing
from app.calls import transcript
from app.calls.models import Call
from app.core.db import Database
from app.core.errors import ProblemError
from app.evals.jobs import EVALUATE_CALL
from app.llms.runtime import runtime
from app.simulator import service
from app.simulator.models import SimulationRun
from app.simulator.persona import ExtractionFailed, extract_brief
from app.testing import dispatch
from app.testing.charges import charge_run, merge_usage

logger = logging.getLogger(__name__)
DISPATCH_SIMULATION = "dispatch_simulation"
LOST_DISPATCH_S = 30 * 60


async def enqueue_runs(queue: Any, workspace_id: str, run_ids: list[str]) -> None:
    if queue is None:
        return
    for run_id in run_ids:
        await queue.enqueue(DISPATCH_SIMULATION, workspace_id, run_id)


async def _extract(db: Database, settings: Any, workspace_id: str, run_id: str) -> str | None:
    """Write the persona brief of a persona run from a base call. Returns an error or None."""
    async with db.transaction(workspace_id=workspace_id) as session:
        run = await session.get(SimulationRun, run_id)
        if run is None or run.persona_brief or run.base_call_id is None:
            return None
        base = await session.get(Call, run.base_call_id)
        if base is None:
            return "The base call is no longer available."
        messages = transcript.read(base).messages
        model = str((run.settings or {}).get("persona_model") or settings.simulator_model)
    rt = runtime()
    try:
        brief, usage = await extract_brief(rt.llm, model, messages, timeout_s=settings.sim_timeout_s)
    except ExtractionFailed as exc:
        return f"Could not write the persona brief: {exc}"
    async with db.transaction(workspace_id=workspace_id) as session:
        run = await session.get(SimulationRun, run_id, with_for_update=True)
        if run is None or run.status != "pending":
            return None
        try:
            charge = await charge_run(
                session,
                workspace_id=workspace_id,
                run_id=run.id,
                feature_key="simulation.persona_extraction",
                usage=usage.as_usage(),
                part="persona_extraction",
                ref_type="simulation_run",
                ref_id=run.id,
            )
        except ProblemError as exc:
            if exc.code == "insufficient_credit":
                return "insufficient credit"
            raise
        run.persona_brief = brief
        run.persona_source = "extracted"
        run.usage = merge_usage(run.usage or {}, usage.as_usage())
        run.cost_usd = (run.cost_usd or Decimal(0)) + charge.billable_usd
    return None


async def _fail(db: Database, workspace_id: str, run_id: str, message: str) -> None:
    async with db.transaction(workspace_id=workspace_id) as session:
        run = await session.get(SimulationRun, run_id, with_for_update=True)
        if run is not None:
            await service.fail_run(session, run, message)
            experiment_id = run.experiment_id
        else:
            experiment_id = None
    if experiment_id:
        await fire_if_finished(db, workspace_id, experiment_id)


async def dispatch_simulation(ctx: dict[str, Any], workspace_id: str, simulation_run_id: str) -> str:
    db: Database = ctx["db"]
    settings = ctx["settings"]
    async with db.transaction(workspace_id=workspace_id) as session:
        run = await session.get(SimulationRun, simulation_run_id)
        if run is None or run.status != "pending" or run.dispatched_at is not None:
            return "skipped"
        broke = await billing.get_balance(session, workspace_id) <= 0
        needs_brief = run.mode == "persona" and not run.persona_brief and run.base_call_id is not None
    if broke:
        await _fail(db, workspace_id, simulation_run_id, "insufficient credit")
        return "insufficient_credit"
    if needs_brief:
        problem = await _extract(db, settings, workspace_id, simulation_run_id)
        if problem:
            await _fail(db, workspace_id, simulation_run_id, problem)
            return "failed"
    redis = ctx["redis"]
    if not await dispatch.acquire(redis, workspace_id, simulation_run_id, settings.sim_max_concurrency):
        await ctx["jobs"].enqueue(
            DISPATCH_SIMULATION, workspace_id, simulation_run_id, defer_by_s=dispatch.RETRY_DEFER_S
        )
        return "waiting"
    async with db.transaction(workspace_id=workspace_id) as session:
        run = await session.get(SimulationRun, simulation_run_id, with_for_update=True)
        if run is None or run.status != "pending":
            await dispatch.release(redis, workspace_id, simulation_run_id)
            return "skipped"
        run.dispatched_at = datetime.now(UTC)
    await dispatch.textsim_queue(ctx).enqueue(
        RUN_SIMULATION, simulation_run_id, job_id=f"textsim:{simulation_run_id}"
    )
    return "dispatched"


async def fire_if_finished(db: Database, workspace_id: str, experiment_id: str) -> bool:
    async with db.transaction(workspace_id=workspace_id) as session:
        exp = await service.claim_finished_hooks(session, experiment_id)
        source = exp.source if exp is not None else None
    if source is None:
        return False
    await service.fire_hooks(source, workspace_id, experiment_id)
    return True


async def after_result(
    db: Database,
    redis: Any,
    queue: Any,
    workspace_id: str,
    run_id: str,
    experiment_id: str | None,
    base_group: str | None,
    base_call_id: str | None,
) -> None:
    await dispatch.release(redis, workspace_id, run_id)
    if base_group and base_call_id and queue is not None:
        await queue.enqueue(
            EVALUATE_CALL, workspace_id, base_call_id, base_group, job_id=f"evaluate:{base_group}"
        )
    if experiment_id:
        await fire_if_finished(db, workspace_id, experiment_id)


async def sweep_simulations(ctx: dict[str, Any]) -> int:
    """Fail runs whose runner went silent; returns how many were failed."""
    db: Database = ctx["db"]
    redis = ctx["redis"]
    async with db.transaction() as session:
        rows = (
            await session.execute(
                text("select run_id, workspace_id from simulation_runs_stale(:stale, :lost)"),
                {"stale": dispatch.STALE_RUN_S, "lost": LOST_DISPATCH_S},
            )
        ).all()
    for run_id, workspace_id in rows:
        await _fail(db, workspace_id, run_id, "The simulation runner stopped answering.")
        await dispatch.release(redis, workspace_id, run_id)
    return len(rows)


async def purge_simulation_data(ctx: dict[str, Any]) -> int:
    """Clear persona briefs and simulated transcripts whose base call's transcript is gone."""
    db: Database = ctx["db"]
    async with db.transaction() as session:
        purged = (await session.execute(text("select simulation_data_purge()"))).scalar()
    return int(purged or 0)
