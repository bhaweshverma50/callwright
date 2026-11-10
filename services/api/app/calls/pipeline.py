"""Post-call step table and runner (003 T077 to T080, T093, T106; architecture section 6, R14).

Steps run in a fixed order, one ``call_pipeline_steps`` row per ``(call_id, step)``:

| step                | blocking | what it does                                                   |
|---------------------|----------|----------------------------------------------------------------|
| finalize_transcript | yes      | ordered transcript items and latency statistics from events     |
| price_and_charge    | yes      | 001 pricing and one ledger charge (``call_charge:{call_id}``)  |
| analyze             | no       | 007 handler (summary, sentiment, variables); skipped if none   |
| evaluate            | no       | 007 handler (evaluators); skipped if none                      |
| notify_analyzed     | no       | customer ``call_analyzed`` webhook (enqueued once per call)    |
| complete            | yes      | ``completed`` (or ``voicemail``), pipeline status              |

Calls whose origin is not billable skip ``price_and_charge``, and those that never reach customers
skip ``notify_analyzed`` (``calls.origins``; simulations are billed as feature charges by 008).
Each step locks its row with ``FOR UPDATE SKIP LOCKED`` and commits its effects and its ``done``
mark in one transaction (under the call row lock), so a step runs once even when two runners race
or a run is replayed. A failing blocking step stops the
chain and is retried with backoff; after ``MAX_BLOCKING_ATTEMPTS`` the pipeline is ``blocked``
and an alert is logged. A failing non-blocking step is recorded as a warning and the chain
continues.
"""

from __future__ import annotations

import logging
import statistics
from collections.abc import Awaitable, Callable, Mapping
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Final, Literal, get_args

from callwright_contract.adapters import AdapterCatalog
from opentelemetry import trace
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing import service as billing
from app.calls import components as comp
from app.calls import lifecycle
from app.calls.lookups import config_for
from app.calls.models import Call, CallEvent, CallPipelineStep
from app.calls.origins import policy
from app.calls.ports import registry
from app.core.db import Database
from app.core.queue import Deferred
from app.webhooks_out import service as webhooks

logger = logging.getLogger(__name__)
tracer = trace.get_tracer("callwright.calls.pipeline")

MAX_BLOCKING_ATTEMPTS = 5
RETRY_BASE_S = 10.0


@dataclass(frozen=True)
class StepSpec:
    name: str
    blocking: bool


BLOCKING_STEPS = frozenset({"finalize_transcript", "price_and_charge", "complete"})
PipelineStep = Literal[
    "finalize_transcript", "price_and_charge", "analyze", "evaluate", "notify_analyzed", "complete"
]
PIPELINE_STEPS: Final[tuple[PipelineStep, ...]] = get_args(PipelineStep)
STEPS: tuple[StepSpec, ...] = tuple(StepSpec(name, name in BLOCKING_STEPS) for name in PIPELINE_STEPS)

Outcome = Literal["done", "skipped"]
# Jobs an external handler wants enqueued once its step commits (007 enqueues evaluate_call).
_step_deferred: ContextVar[Deferred | None] = ContextVar("pipeline_step_deferred", default=None)


def step_deferred() -> Deferred | None:
    """The running ``analyze``/``evaluate`` step's post-commit job list (None outside a step)."""
    return _step_deferred.get()


@dataclass
class StepContext:
    session: AsyncSession
    call: Call
    config: Mapping[str, Any] | None
    catalog: AdapterCatalog
    deferred: Deferred
    now: datetime
    recordings_bucket: str | None


StepHandler = Callable[[StepContext], Awaitable[Outcome]]


def latency_stats(turns: list[CallEvent]) -> dict[str, Any]:
    """data-model section 7, from ``turn`` events with ``turn_index > 0``; greeting from turn 0."""
    replies = [t for t in turns if (t.turn_index or 0) > 0]
    greeting = next((t.e2e_ms for t in turns if t.turn_index == 0 and t.e2e_ms is not None), None)
    e2e = sorted(t.e2e_ms for t in replies if t.e2e_ms is not None)

    def avg(values: list[int]) -> int | None:
        return round(statistics.fmean(values)) if values else None

    def pct(p: float) -> int | None:
        if not e2e:
            return None
        index = max(0, min(len(e2e) - 1, round(p * (len(e2e) - 1))))
        return e2e[index]

    return {
        "turns": len(replies),
        "greeting_ms": greeting,
        "e2e_p50_ms": pct(0.5),
        "e2e_p95_ms": pct(0.95),
        "e2e_avg_ms": avg(e2e),
        "e2e_max_ms": e2e[-1] if e2e else None,
        "stt_final_avg_ms": avg([t.stt_final_ms for t in replies if t.stt_final_ms is not None]),
        "eou_delay_avg_ms": avg([t.eou_delay_ms for t in replies if t.eou_delay_ms is not None]),
        "llm_ttft_avg_ms": avg([t.llm_ttft_ms for t in replies if t.llm_ttft_ms is not None]),
        "tts_ttfb_avg_ms": avg([t.tts_ttfb_ms for t in replies if t.tts_ttfb_ms is not None]),
    }


async def finalize_transcript(ctx: StepContext) -> Outcome:
    rows = list(
        (
            await ctx.session.execute(
                select(CallEvent)
                .where(CallEvent.call_id == ctx.call.id, CallEvent.type.in_(("transcript_item", "turn")))
                .order_by(CallEvent.seq)
            )
        ).scalars()
    )
    items = [dict(r.payload.get("item") or {}) for r in rows if r.type == "transcript_item"]
    ctx.call.transcript = {"items": items}
    ctx.call.latency_stats = latency_stats([r for r in rows if r.type == "turn"])
    return "done"


async def price_and_charge(ctx: StepContext) -> Outcome:
    call = ctx.call
    if not policy(call.origin).billable or call.connected_at is None or call.ended_at is None:
        return "skipped"
    if ctx.config is None:
        raise LookupError(f"agent version {call.agent_version_id} is not available")
    components = comp.resolve(ctx.config, ctx.catalog).pricing(call.usage)
    duration_ms = max(0, int((call.ended_at - call.connected_at).total_seconds() * 1000))
    cost = await billing.charge_call(
        ctx.session,
        billing.CallUsage(
            workspace_id=call.workspace_id,
            call_id=call.id,
            agent_version_id=call.agent_version_id,
            started_at=call.connected_at,
            duration_ms=duration_ms,
            components=components,
            meters=comp.usage_meters(call.usage),
        ),
    )
    call.cost_total_usd = cost.total_usd
    call.cost_breakdown = billing.call_cost_json(cost)
    return "done"


def _external_step(name: str) -> StepHandler:
    async def run(ctx: StepContext) -> Outcome:
        handler = registry.step_handlers.get(name)
        if handler is None or ctx.call.connected_at is None:
            return "skipped"
        token = _step_deferred.set(ctx.deferred)
        try:
            await handler(ctx.call.id, ctx.session)
        finally:
            _step_deferred.reset(token)
        return "done"

    return run


async def notify_analyzed(ctx: StepContext) -> Outcome:
    call = ctx.call
    if not policy(call.origin).reaches_customer or webhooks.webhook_settings(ctx.config)[0] is None:
        return "skipped"
    url = None
    if (
        call.recording_enabled
        and call.recording_status == "available"
        and call.recording_key
        and registry.signer is not None
        and ctx.recordings_bucket
    ):
        url = registry.signer.presign_get(
            ctx.recordings_bucket, call.recording_key, webhooks.RECORDING_URL_TTL_S
        )
    await lifecycle.notify(
        ctx.session, call, "call_analyzed", deferred=ctx.deferred, recording_url=url, now=ctx.now
    )
    return "done"


async def complete(ctx: StepContext) -> Outcome:
    await lifecycle.finalize(ctx.session, ctx.call, ctx.now)
    return "done"


HANDLERS: dict[str, StepHandler] = {
    "finalize_transcript": finalize_transcript,
    "price_and_charge": price_and_charge,
    "analyze": _external_step("analyze"),
    "evaluate": _external_step("evaluate"),
    "notify_analyzed": notify_analyzed,
    "complete": complete,
}


@dataclass
class PipelineRun:
    status: Literal["finished", "busy", "retry", "blocked", "not_ready"]
    deferred: Deferred = field(default_factory=Deferred)
    retry_in_s: float | None = None
    steps: dict[str, str] = field(default_factory=dict)


async def _start(session: AsyncSession, call_id: str, workspace_id: str, replay: bool) -> Call | None:
    call = (
        await session.execute(select(Call).where(Call.id == call_id).with_for_update())
    ).scalar_one_or_none()
    if call is None:
        return None
    if call.status == "ended":
        call.status = "processing"
        call.pipeline_status = "running"
    elif call.status not in ("processing", "completed", "voicemail"):
        return None
    elif call.status != "processing" and not replay:
        return None
    for spec in STEPS:
        await session.execute(
            text(
                "insert into call_pipeline_steps (call_id, step, workspace_id, blocking) "
                "values (:call, :step, :ws, :blocking) on conflict do nothing"
            ),
            {"call": call_id, "step": spec.name, "ws": workspace_id, "blocking": spec.blocking},
        )
    if replay:
        await session.execute(
            update(CallPipelineStep)
            .where(CallPipelineStep.call_id == call_id)
            .values(status="pending", attempts=0, last_error=None)
        )
    return call


async def run(
    db: Database,
    workspace_id: str,
    call_id: str,
    *,
    catalog: AdapterCatalog,
    recordings_bucket: str | None = None,
    replay: bool = False,
    now: datetime | None = None,
) -> PipelineRun:
    """Run every pending step for ``call_id`` in order (see module docstring)."""
    result = PipelineRun(status="finished")
    async with db.transaction(workspace_id=workspace_id) as session:
        call = await _start(session, call_id, workspace_id, replay)
        if call is None:
            result.status = "not_ready"
            return result
    for spec in STEPS:
        with tracer.start_as_current_span(f"pipeline.{spec.name}", attributes={"call_id": call_id}):
            outcome = await _run_step(
                db, workspace_id, call_id, spec, catalog, recordings_bucket, now, result
            )
        if outcome == "stop":
            return result
    return result


async def _run_step(
    db: Database,
    workspace_id: str,
    call_id: str,
    spec: StepSpec,
    catalog: AdapterCatalog,
    recordings_bucket: str | None,
    now: datetime | None,
    result: PipelineRun,
) -> Literal["continue", "stop"]:
    async with db.transaction(workspace_id=workspace_id) as session:
        # Lock order everywhere is call row, then step row (``_start`` takes them the same way).
        call = (await session.execute(select(Call).where(Call.id == call_id).with_for_update())).scalar_one()
        step = (
            await session.execute(
                select(CallPipelineStep)
                .where(CallPipelineStep.call_id == call_id, CallPipelineStep.step == spec.name)
                .with_for_update(skip_locked=True)
            )
        ).scalar_one_or_none()
        if step is None:
            result.status = "busy"  # another runner holds this step
            return "stop"
        if step.status in ("done", "skipped") or (step.status == "failed" and not spec.blocking):
            result.steps[spec.name] = step.status
            return "continue"
        config = await config_for(session, call)
        stamp = now or datetime.now(UTC)
        ctx = StepContext(session, call, config, catalog, Deferred(), stamp, recordings_bucket)
        step.started_at = stamp
        step.attempts += 1
        try:
            async with session.begin_nested():
                outcome = await HANDLERS[spec.name](ctx)
                await session.flush()
        except Exception as exc:
            # The savepoint rolled back the handler's writes; reload what it may have touched.
            await session.refresh(step)
            await session.refresh(call)
            step.last_error = f"{type(exc).__name__}: {exc}"[:2048]
            logger.warning("pipeline step %s failed for %s: %s", spec.name, call_id, step.last_error)
            if not spec.blocking:
                step.status = "failed"
                step.finished_at = stamp
                if spec.name not in (call.pipeline_warnings or []):
                    call.pipeline_warnings = [*(call.pipeline_warnings or []), spec.name]
                result.steps[spec.name] = "failed"
                return "continue"
            if step.attempts >= MAX_BLOCKING_ATTEMPTS:
                step.status = "failed"
                step.finished_at = stamp
                call.pipeline_status = "blocked"
                result.status = "blocked"
                logger.error(
                    "post-call pipeline blocked: call_id=%s step=%s attempts=%s error=%s",
                    call_id,
                    spec.name,
                    step.attempts,
                    step.last_error,
                    extra={"alert": "pipeline_blocked", "call_id": call_id, "step": spec.name},
                )
                trace.get_current_span().add_event(
                    "pipeline_blocked", {"call_id": call_id, "step": spec.name}
                )
            else:
                step.status = "pending"
                result.status = "retry"
                result.retry_in_s = RETRY_BASE_S * (2 ** (step.attempts - 1))
            result.steps[spec.name] = step.status
            return "stop"
        step.status = outcome
        step.finished_at = stamp
        step.last_error = None
        result.steps[spec.name] = outcome
        result.deferred.extend(ctx.deferred)
    return "continue"
