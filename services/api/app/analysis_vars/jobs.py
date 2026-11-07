"""Post-call analysis job (007 T020, T022, T068; FR-002 to FR-005, research R6, R11).

``analyze_call`` runs inside the 003 pipeline's ``analyze`` step (same transaction, call row
locked), so the ``call_analyzed`` webhook that follows carries the summary. Order: balance check
(skip with ``insufficient_credit`` at or below zero), extraction through the ``llms`` client,
the call write via ``calls.service.set_analysis``, then one ``post_call_analysis`` feature
charge keyed by call and attempt. A pipeline replay of a completed analysis does nothing.

``rerun_analysis`` (arq) re-runs it after ``POST /calls/{id}/analysis/rerun`` raised the attempt.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from opentelemetry import trace
from sqlalchemy.ext.asyncio import AsyncSession

from app.analysis_vars import extractor
from app.analysis_vars.models import CallAnalysis
from app.analysis_vars.service import active_variables, snapshot
from app.billing import service as billing
from app.calls import service as calls_service
from app.calls.models import Call
from app.core.errors import ProblemError
from app.evals.context import build_context
from app.evals.runtime import runtime
from app.evals.settings import default_judge_model
from app.evals.short_call import too_short
from app.llms.client import billable_cost

logger = logging.getLogger(__name__)
tracer = trace.get_tracer("app.analysis_vars")
RERUN_ANALYSIS = "rerun_analysis"
SIX = Decimal("0.000001")


async def ensure_row(session: AsyncSession, call: Call) -> CallAnalysis:
    row = await session.get(CallAnalysis, call.id)
    if row is None:
        row = CallAnalysis(call_id=call.id, workspace_id=call.workspace_id, status="pending", attempt=1)
        session.add(row)
        await session.flush()
    return row


async def analyze_call(session: AsyncSession, call_id: str, *, rerun: bool = False) -> CallAnalysis | None:
    """Analyse ``call_id`` in the caller's transaction. Returns the analysis row."""
    rt = runtime()
    call = await session.get(Call, call_id)
    if call is None:
        return None
    row = await ensure_row(session, call)
    if not rerun and row.status in ("completed", "skipped", "error") and row.analyzed_at is not None:
        return row  # pipeline replay: analysed once already
    with tracer.start_as_current_span("analysis.analyze_call", attributes={"call_id": call_id}) as span:
        variables = snapshot(await active_variables(session, call.agent_id))
        ctx = await build_context(session, call)
        model = extractor.model_for(ctx.config, default_judge_model(rt.settings))
        span.set_attribute("llm.model", model)
        row.model = model
        row.variable_snapshot = variables
        row.updated_at = row.analyzed_at = datetime.now(UTC)
        row.error = row.skip_reason = None
        if not rerun and too_short(call, rt.settings):
            row.status, row.skip_reason = "skipped", "too_short"
            await session.flush()
            return row
        if await billing.get_balance(session, call.workspace_id) <= 0:
            row.status, row.skip_reason = "skipped", "insufficient_credit"
            await session.flush()
            return row
        try:
            result = await extractor.extract(
                rt.llm,
                model,
                messages=ctx.messages,
                tools=ctx.tools,
                variables=variables,
                timeout_s=rt.settings.eval_timeout_s,
            )
        except extractor.ExtractionFailed as exc:
            row.status, row.error = "error", str(exc)[:500]
            span.record_exception(exc)
            await session.flush()
            return row
        raw = result.usage.raw_cost_usd.quantize(SIX)
        try:
            charge = await billing.charge_feature(
                session,
                workspace_id=call.workspace_id,
                feature_key="post_call_analysis",
                quantity=Decimal(result.usage.input_tokens + result.usage.output_tokens),
                unit="tokens",
                raw_cost_usd=raw,
                billable_cost_usd=billable_cost(result.usage.raw_cost_usd),
                idempotency_key=f"analysis:{call_id}:{row.attempt}",
                ref_type="call",
                ref_id=call_id,
            )
        except ProblemError as exc:
            if exc.code != "insufficient_credit":
                raise
            row.status, row.skip_reason = "skipped", "insufficient_credit"
            await session.flush()
            return row
        row.status = "completed"
        row.summary = result.summary
        row.sentiment = result.sentiment
        row.values = result.values
        row.input_tokens = result.usage.input_tokens
        row.output_tokens = result.usage.output_tokens
        row.raw_cost_usd = raw
        row.charge_txn_id = charge.txn.id if charge.txn else None
        await calls_service.set_analysis(
            session, call_id, summary=result.summary, sentiment=result.sentiment, values=result.values
        )
        await session.flush()
        return row


async def pipeline_handler(call_id: str, session: AsyncSession) -> None:
    """003 ``analyze`` step handler."""
    await analyze_call(session, call_id)


async def rerun_analysis(ctx: dict[str, Any], workspace_id: str, call_id: str) -> str:
    try:
        async with ctx["db"].transaction(workspace_id=workspace_id) as session:
            row = await analyze_call(session, call_id, rerun=True)
            return row.status if row is not None else "missing"
    except Exception:
        # The rerun endpoint already marked the row running; never leave it spinning.
        async with ctx["db"].transaction(workspace_id=workspace_id) as session:
            row = await session.get(CallAnalysis, call_id)
            if row is not None and row.status == "running":
                row.status, row.error = "error", "The analysis could not be saved. Try re-running it."
                row.updated_at = datetime.now(UTC)
        raise
