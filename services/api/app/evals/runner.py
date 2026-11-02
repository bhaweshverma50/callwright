"""Evaluator runs (007 T037, T068, T083; FR-013 to FR-018, FR-037, research R5, R6).

``start_group`` (inside the caller's transaction) claims the call's one active run group, snapshots
each enabled evaluator's effective settings and creates its run: ``pending``, or ``skipped`` with
``not_sampled`` when automatic sampling leaves the call out. A second active group for the same
call is refused (``AlreadyRunning``, "Checks are already running"); the same idempotency key
returns the existing group.

``execute_group`` runs the pending runs concurrently (``EVAL_CONCURRENCY``), each with a
timeout and one automatic retry, committing every run as it finishes so the call view fills in
progressively. Model-judge runs check the balance first (skip with ``insufficient_credit``) and
are charged ``eval.<name>`` (``eval.llm_judge_custom`` for custom judges) keyed by the run id;
free evaluators never charge. When the group is done, older runs of the same evaluators on the
call are marked superseded and stay as history.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from opentelemetry import trace
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from app.agents.models import Agent
from app.billing import service as billing
from app.calls.models import Call
from app.core.db import Database
from app.core.errors import ProblemError, field_error, validation_failed
from app.core.ids import new_id
from app.evals import embeddings, sampling
from app.evals.context import build_context
from app.evals.models import EvaluatorResultItem, EvaluatorRun, EvaluatorRunGroup
from app.evals.runtime import QualityRuntime, runtime
from app.evals.scoring import ItemOutcome, run_verdict
from app.evals.service import resolve_all
from app.evals.settings import settings_hash
from app.evals.short_call import too_short
from app.evaluators import audio
from app.evaluators.base import EvalContext, EvalOutcome, EvalTools, Evaluator, Unavailable
from app.evaluators.models import EvaluatorRow, EvaluatorVersion
from app.evaluators.registry import instance_for
from app.llms.client import billable_cost

logger = logging.getLogger(__name__)
tracer = trace.get_tracer("app.evals.runner")
SIX = Decimal("0.000001")
STALE_GROUP = timedelta(minutes=15)
TRIGGERS = ("pipeline", "rerun", "dataset", "simulation")


class AlreadyRunning(Exception):
    pass


def already_running() -> ProblemError:
    return ProblemError(409, "checks_running", "Checks running", "Checks are already running")


@dataclass
class GroupStart:
    group: EvaluatorRunGroup
    runs: list[EvaluatorRun]
    created: bool


def new_group_id() -> str:
    return f"erg_{ULID()}"


async def _release_stale(session: AsyncSession, call_id: str) -> None:
    """A group whose worker died never finishes; after ``STALE_GROUP`` it stops blocking reruns."""
    stale = (
        await session.execute(
            text(
                "update evaluator_run_groups set status = 'done', finished_at = now() "
                "where call_id = :call and status = 'active' and created_at < :before returning run_group_id"
            ),
            {"call": call_id, "before": datetime.now(UTC) - STALE_GROUP},
        )
    ).scalars()
    for group_id in list(stale):
        await session.execute(
            text(
                "update evaluator_runs set status = 'error', error = 'Interrupted before it finished', "
                "completed_at = now() where run_group_id = :g and status in ('pending', 'running')"
            ),
            {"g": group_id},
        )


async def start_group(
    session: AsyncSession,
    call: Call,
    *,
    trigger: str,
    idempotency_key: str,
    evaluator_ids: Sequence[str] | None = None,
    user_id: str | None = None,
) -> GroupStart:
    if trigger not in TRIGGERS:
        raise ValueError(f"unknown trigger {trigger}")
    rt = runtime()
    await _release_stale(session, call.id)
    group_id = new_group_id()
    inserted = (
        await session.execute(
            text(
                "insert into evaluator_run_groups (run_group_id, workspace_id, call_id, trigger, "
                "idempotency_key, created_by) values (:g, :ws, :call, :trigger, :key, :user) "
                "on conflict do nothing returning run_group_id"
            ),
            {
                "g": group_id,
                "ws": call.workspace_id,
                "call": call.id,
                "trigger": trigger,
                "key": idempotency_key,
                "user": user_id,
            },
        )
    ).scalar_one_or_none()
    if inserted is None:
        existing = (
            await session.execute(
                select(EvaluatorRunGroup).where(
                    EvaluatorRunGroup.call_id == call.id, EvaluatorRunGroup.idempotency_key == idempotency_key
                )
            )
        ).scalar_one_or_none()
        if existing is None:
            raise AlreadyRunning()
        runs = list(
            (
                await session.execute(
                    select(EvaluatorRun).where(EvaluatorRun.run_group_id == existing.run_group_id)
                )
            ).scalars()
        )
        return GroupStart(existing, runs, created=False)
    group = await session.get(EvaluatorRunGroup, group_id)
    assert group is not None
    agent = await session.get(Agent, call.agent_id)
    resolved = await resolve_all(session, agent, rt.settings.judge_models) if agent is not None else []
    by_id = {r.row.id: r for r in resolved}
    if evaluator_ids:
        wanted = list(dict.fromkeys(evaluator_ids))
        unknown = [e for e in wanted if e not in by_id or not by_id[e].enabled]
        if unknown:
            raise validation_failed(
                [
                    field_error(
                        "/evaluator_ids", "invalid_format", "Pick checks that are switched on for this agent"
                    )
                ]
            )
        chosen = [by_id[e] for e in wanted]
    else:
        chosen = [r for r in resolved if r.enabled]
    now = datetime.now(UTC)
    runs = []
    # The automatic post-call run skips paid judges on calls too short to judge (free checks run).
    short = trigger == "pipeline" and too_short(call, rt.settings)
    for r in chosen:
        values = dict(r.values)
        run = EvaluatorRun(
            id=new_id("evr"),
            workspace_id=call.workspace_id,
            call_id=call.id,
            agent_id=call.agent_id,
            evaluator_id=r.row.id,
            evaluator_version=r.row.current_version,
            run_group_id=group_id,
            trigger=trigger,
            settings_snapshot=values,
            settings_hash=settings_hash(values),
            status="pending",
            judge_model=str(values.get("judge_model")) if values.get("judge_model") else None,
            created_at=now,
        )
        rate = values.get("sample_rate_pct")
        if short and r.row.cost_class == "llm_judge":
            run.status, run.skip_reason, run.completed_at = "skipped", "too_short", now
        elif (
            isinstance(rate, int)
            and sampling.applies(trigger, call.origin)
            and not sampling.selected(call.id, r.row.name, rate)
        ):
            run.status, run.skip_reason, run.completed_at = "skipped", "not_sampled", now
        runs.append(run)
        session.add(run)
    if not any(run.status == "pending" for run in runs):
        group.status, group.finished_at = "done", now
    await session.flush()
    if group.status == "done" and runs:
        await supersede(session, group)
    return GroupStart(group, runs, created=True)


async def supersede(session: AsyncSession, group: EvaluatorRunGroup) -> None:
    await session.execute(
        text(
            "update evaluator_runs o set superseded_at = now() where o.call_id = :call "
            "and o.superseded_at is null and o.run_group_id <> :g and o.evaluator_id in "
            "(select evaluator_id from evaluator_runs where run_group_id = :g)"
        ),
        {"call": group.call_id, "g": group.run_group_id},
    )


@dataclass
class Planned:
    run_id: str
    evaluator: Evaluator
    row: EvaluatorRow
    settings: dict[str, Any]


def feature_key(row: EvaluatorRow) -> str:
    return "eval.llm_judge_custom" if row.evaluator_type == "llm_judge_custom" else f"eval.{row.name}"


def tools_for(db: Database, workspace_id: str, rt: QualityRuntime, settings: dict[str, Any]) -> EvalTools:
    async def neighbours(ctx: EvalContext, values: Any) -> embeddings.Neighbours:
        async with db.transaction(workspace_id=workspace_id) as session:
            return await embeddings.neighbours(session, rt.embedder, ctx, values)

    return EvalTools(
        judge=rt.judge,
        read_levels=audio.read_levels,
        neighbours=neighbours if rt.embedder is not None else None,
        judge_model=str(settings.get("judge_model") or rt.settings.default_judge_model),
        cutoff=rt.settings.eval_judge_pass_cutoff,
    )


async def _skip(db: Database, workspace_id: str, run_id: str, reason: str) -> None:
    async with db.transaction(workspace_id=workspace_id) as session:
        run = await session.get(EvaluatorRun, run_id)
        if run is not None:
            run.status, run.skip_reason, run.completed_at = "skipped", reason, datetime.now(UTC)


async def _write(db: Database, workspace_id: str, plan: Planned, outcome: EvalOutcome) -> None:
    async with db.transaction(workspace_id=workspace_id) as session:
        run = await session.get(EvaluatorRun, plan.run_id, with_for_update=True)
        if run is None or run.status not in ("pending", "running"):
            return
        charge_txn = None
        raw = outcome.raw_cost_usd.quantize(SIX)
        if plan.row.cost_class == "llm_judge" and (outcome.input_tokens or outcome.output_tokens):
            try:
                charge = await billing.charge_feature(
                    session,
                    workspace_id=workspace_id,
                    feature_key=feature_key(plan.row),
                    quantity=Decimal(outcome.input_tokens + outcome.output_tokens),
                    unit="tokens",
                    raw_cost_usd=raw,
                    billable_cost_usd=billable_cost(outcome.raw_cost_usd),
                    idempotency_key=f"eval_run:{run.id}",
                    ref_type="call",
                    ref_id=run.call_id,
                )
            except ProblemError as exc:
                if exc.code != "insufficient_credit":
                    raise
                run.status, run.skip_reason, run.completed_at = (
                    "skipped",
                    "insufficient_credit",
                    datetime.now(UTC),
                )
                return
            charge_txn = charge.txn.id if charge.txn else None
        verdict, score = run_verdict(
            [ItemOutcome(i.verdict, i.score) for i in outcome.items],
            max_failed_items=plan.evaluator.max_failed_items(plan.settings),
        )
        rationale = outcome.rationale or "; ".join(i.rationale for i in outcome.items if i.rationale)[:2000]
        if verdict != "not_applicable" and not rationale:
            rationale = "No reason was given."
        run.status = "completed"
        run.verdict = verdict
        run.score = score
        run.rationale = rationale or None
        run.judge_model = outcome.judge_model or run.judge_model
        run.input_tokens = outcome.input_tokens
        run.output_tokens = outcome.output_tokens
        run.raw_cost_usd = raw
        run.charge_txn_id = charge_txn
        run.completed_at = datetime.now(UTC)
        for position, item in enumerate(outcome.items):
            session.add(
                EvaluatorResultItem(
                    workspace_id=workspace_id,
                    run_id=run.id,
                    position=position,
                    turn_index=item.turn_index,
                    flow_node_id=item.flow_node_id,
                    flow_node_label=item.flow_node_label,
                    start_ms=item.start_ms,
                    duration_ms=item.duration_ms,
                    verdict=item.verdict,
                    score=item.score,
                    rationale=item.rationale
                    or ("" if item.verdict == "not_applicable" else "No reason was given."),
                    evidence=dict(item.evidence),
                )
            )


async def execute_run(
    db: Database, workspace_id: str, plan: Planned, ctx: EvalContext, rt: QualityRuntime
) -> str:
    with tracer.start_as_current_span(
        "evals.run",
        attributes={"call_id": ctx.call_id, "evaluator_name": plan.row.name, "run_id": plan.run_id},
    ) as span:
        error = "The check could not run"
        for attempt in (1, 2):
            async with db.transaction(workspace_id=workspace_id) as session:
                run = await session.get(EvaluatorRun, plan.run_id, with_for_update=True)
                if run is None or run.status not in ("pending", "running"):
                    return run.status if run is not None else "missing"
                run.status, run.attempt = "running", attempt
                run.started_at = run.started_at or datetime.now(UTC)
                if (
                    plan.row.cost_class == "llm_judge"
                    and await billing.get_balance(session, workspace_id) <= 0
                ):
                    run.status, run.skip_reason, run.completed_at = (
                        "skipped",
                        "insufficient_credit",
                        datetime.now(UTC),
                    )
                    return "skipped"
            tools = tools_for(db, workspace_id, rt, plan.settings)
            try:
                outcome = await asyncio.wait_for(
                    plan.evaluator.evaluate(ctx, plan.settings, tools), timeout=rt.settings.eval_timeout_s
                )
            except (Unavailable, TimeoutError) as exc:
                error = str(exc) or "The check timed out"
                span.add_event("retry" if attempt == 1 else "error", {"reason": error})
                continue
            except Exception as exc:
                logger.exception("evaluator %s failed on %s", plan.row.name, ctx.call_id)
                error = f"The check failed: {type(exc).__name__}"
                continue
            await _write(db, workspace_id, plan, outcome)
            return "completed"
        async with db.transaction(workspace_id=workspace_id) as session:
            run = await session.get(EvaluatorRun, plan.run_id)
            if run is not None and run.status in ("pending", "running"):
                run.status, run.error, run.completed_at = "error", error[:500], datetime.now(UTC)
        return "error"


async def execute_group(
    db: Database, workspace_id: str, run_group_id: str, *, rt: QualityRuntime | None = None
) -> str:
    rt = rt or runtime()
    async with db.transaction(workspace_id=workspace_id) as session:
        group = await session.get(EvaluatorRunGroup, run_group_id)
        if group is None:
            return "missing"
        if group.status == "done":
            return "done"
        call = await session.get(Call, group.call_id)
        if call is None:
            return "missing"
        runs = list(
            (
                await session.execute(
                    select(EvaluatorRun).where(
                        EvaluatorRun.run_group_id == run_group_id,
                        EvaluatorRun.status.in_(("pending", "running")),
                    )
                )
            ).scalars()
        )
        plans: list[Planned] = []
        for run in runs:
            row = await session.get(EvaluatorRow, run.evaluator_id)
            version = await session.get(EvaluatorVersion, (run.evaluator_id, run.evaluator_version))
            if row is None or version is None:
                continue
            evaluator_type = row.evaluator_type if row.kind == "custom" else row.name
            plans.append(
                Planned(
                    run.id,
                    instance_for(evaluator_type, version.definition or {}),
                    row,
                    dict(run.settings_snapshot),
                )
            )
        ctx = await build_context(
            session, call, run_id=run_group_id, recordings_bucket=rt.settings.recordings_bucket
        )
    semaphore = asyncio.Semaphore(rt.settings.eval_concurrency)

    async def guarded(plan: Planned) -> str:
        async with semaphore:
            return await execute_run(db, workspace_id, plan, ctx, rt)

    with tracer.start_as_current_span("evals.group", attributes={"call_id": ctx.call_id, "runs": len(plans)}):
        await asyncio.gather(*(guarded(p) for p in plans))
    async with db.transaction(workspace_id=workspace_id) as session:
        group = await session.get(EvaluatorRunGroup, run_group_id, with_for_update=True)
        if group is None or group.status == "done":
            return "done"
        open_runs = (
            await session.execute(
                text(
                    "select count(*) from evaluator_runs where run_group_id = :g and status in "
                    "('pending', 'running')"
                ),
                {"g": run_group_id},
            )
        ).scalar_one()
        if open_runs:
            return "active"
        group.status, group.finished_at = "done", datetime.now(UTC)
        await supersede(session, group)
    return "done"
