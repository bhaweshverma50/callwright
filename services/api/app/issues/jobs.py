"""Issue jobs on the API's arq worker (009 T021, T040, T055, T056).

* ``detect_issues(workspace_id, run_id)``: one detection run (``detection.py``), charged once
  as ``issues.detect``. A run that fails (worker error, balance at zero) is marked failed with a
  message saying what to do.
* ``finalize_validation(workspace_id, experiment_id)``: queued by 008's completion hook when a
  validation batch finishes (and by the sweeper). Writes the evidence once both batches are final
  and evaluated; until then it re-queues itself every ``validation.RETRY_S`` seconds.
* ``sweep_issues`` (cron, every minute): detections running longer than ``STALE_DETECTION_S``
  fail; validations whose batches are both final get a finalize job (covers a lost hook).
* ``audit_applied_issues`` (cron, daily): SC-001, every applied issue has a passing attempt whose
  variant hash matches the applied version (copied tools mapped back). Mismatches are logged as
  errors and counted.

Spans ``issues.detect`` and ``issues.finalize_validation`` carry ``issue.agent_id`` and
``issue.id`` (OpenTelemetry, exported when an OTLP endpoint is configured).
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from opentelemetry import trace
from sqlalchemy import text

from app.core.db import Database
from app.core.errors import ProblemError
from app.issues import charges, detection, validation
from app.issues.models import IssueDetectionRun
from app.issues.runtime import model as issues_model
from app.llms.runtime import runtime

logger = logging.getLogger(__name__)
tracer = trace.get_tracer("app.issues")

DETECT_ISSUES = "detect_issues"
FINALIZE_VALIDATION = "finalize_validation"
STALE_DETECTION_S = 15 * 60


async def _fail_detection(db: Database, workspace_id: str, run_id: uuid.UUID, message: str) -> None:
    async with db.transaction(workspace_id=workspace_id) as session:
        run = await session.get(IssueDetectionRun, run_id, with_for_update=True)
        if run is not None and run.status == "running":
            run.status = "failed"
            run.error_message = message[:2000]
            run.finished_at = datetime.now(UTC)


async def detect_issues(ctx: dict[str, Any], workspace_id: str, run_id: str) -> str:
    db: Database = ctx["db"]
    settings = ctx["settings"]
    rid = uuid.UUID(run_id)
    with tracer.start_as_current_span("issues.detect") as span:
        span.set_attribute("issue.detection_run_id", run_id)
        try:
            async with db.transaction(workspace_id=workspace_id) as session:
                run = await session.get(IssueDetectionRun, rid)
                if run is None or run.status != "running":
                    return "skipped"
                span.set_attribute("issue.agent_id", run.agent_id)
                gathered = await detection.gather(session, run, settings)
            usage = detection.Usage()
            fresh = await detection.embed_missing(gathered, usage)
            vectors = {**gathered.cached, **fresh}
            plans = detection.plan_clusters(gathered, vectors)
            for plan in plans:
                if plan.decision.action in ("create", "recurrence"):
                    members = [vectors[(f.result_id, f.node_key)] for f in plan.failures]
                    reasons = detection.representative(plan.failures, members, plan.centroid)
                    await detection.name_plan(
                        plan, gathered.evaluators.get(plan.evaluator_id), reasons, usage
                    )

            async with db.transaction(workspace_id=workspace_id) as session:
                run = await session.get(IssueDetectionRun, rid, with_for_update=True)
                if run is None or run.status != "running":
                    return "skipped"
                created, updated = await detection.write(session, run, gathered, plans, fresh)
                raw = charges.raw_cost(
                    issues_model(runtime().settings),
                    usage.input_tokens,
                    usage.output_tokens,
                    embed_raw=usage.embed_raw,
                )
                billed = await charges.charge(
                    session,
                    workspace_id=workspace_id,
                    feature_key=charges.DETECT,
                    key=charges.detect_key(run_id),
                    raw=raw,
                    tokens=usage.input_tokens + usage.output_tokens + usage.embed_tokens,
                    ref_type="agent",
                    ref_id=run.agent_id,
                )
                run.status = "completed"
                run.calls_scanned = gathered.calls_scanned
                run.failures_scanned = len(gathered.failures)
                run.issues_created = created
                run.issues_updated = updated
                run.cost_usd = billed
                run.finished_at = datetime.now(UTC)
            span.set_attribute("issue.created", created)
            span.set_attribute("issue.updated", updated)
            return "completed"
        except ProblemError as exc:
            message = (
                "Your balance ran out. Add funds, then run detection again."
                if exc.code == "insufficient_credit"
                else str(exc.detail or exc.title)
            )
            await _fail_detection(db, workspace_id, rid, message)
            return "failed"
        except LookupError as exc:
            await _fail_detection(db, workspace_id, rid, str(exc))
            return "failed"
        except Exception:
            logger.exception("issue detection failed", extra={"detection_run_id": run_id})
            await _fail_detection(
                db, workspace_id, rid, "Detection stopped because of an internal error. Run it again."
            )
            return "failed"


async def finalize_validation(ctx: dict[str, Any], workspace_id: str, experiment_id: str) -> str:
    db: Database = ctx["db"]
    settings = ctx["settings"]
    with tracer.start_as_current_span("issues.finalize_validation") as span:
        span.set_attribute("issue.experiment_id", experiment_id)
        async with db.transaction(workspace_id=workspace_id) as session:
            attempt = await validation.attempt_for_experiment(session, experiment_id)
            if attempt is None or attempt.status != "running":
                return "skipped"
            span.set_attribute("issue.id", attempt.issue_id)
            outcome = await validation.finalize(session, settings, attempt.issue_id, attempt.attempt)
        span.set_attribute("issue.outcome", outcome)
        if outcome == "waiting":
            queue = ctx.get("jobs")
            if queue is not None:
                await queue.enqueue(
                    FINALIZE_VALIDATION, workspace_id, experiment_id, defer_by_s=validation.RETRY_S
                )
        return outcome


async def sweep_issues(ctx: dict[str, Any]) -> int:
    db: Database = ctx["db"]
    async with db.transaction() as session:
        stale = (
            await session.execute(
                text("select id, workspace_id from issue_detection_runs_stale(:s)"), {"s": STALE_DETECTION_S}
            )
        ).all()
        due = (
            await session.execute(
                text("select workspace_id, issue_id, attempt from issue_validations_running()")
            )
        ).all()
    for run_id, workspace_id in stale:
        await _fail_detection(
            db, workspace_id, run_id, "Detection took too long and was stopped. Run it again."
        )
    queue = ctx.get("jobs")
    for workspace_id, issue_id, attempt in due:
        async with db.transaction(workspace_id=workspace_id) as session:
            exp = (
                await session.execute(
                    text(
                        "select control_experiment_id from issue_validations "
                        "where issue_id = :i and attempt = :a"
                    ),
                    {"i": issue_id, "a": attempt},
                )
            ).scalar()
        if exp and queue is not None:
            await queue.enqueue(
                FINALIZE_VALIDATION, workspace_id, exp, job_id=f"finalize:{issue_id}:{attempt}"
            )
    return len(stale) + len(due)


async def audit_applied_issues(ctx: dict[str, Any]) -> int:
    """SC-001: count (and log) applied issues without a passing attempt for the applied config."""
    from app.issues.apply import normalised_hash

    db: Database = ctx["db"]
    async with db.transaction() as session:
        rows = (await session.execute(text("select * from issues_applied_audit()"))).mappings().all()
    bad = 0
    for row in rows:
        expected = row["passing_variant_hash"]
        actual = normalised_hash(row["version_config"], list(row["tool_copies"] or []))
        if expected is None or expected != actual:
            bad += 1
            logger.error(
                "applied issue without matching passing validation",
                extra={"issue_id": row["issue_id"], "agent_version_id": row["agent_version_id"]},
            )
    return bad


def on_batch_finished_factory() -> Any:
    async def on_batch_finished(workspace_id: str, experiment_id: str) -> None:
        """008 completion hook: queue the finalize job on the process's job queue."""

        queue = runtime().queue
        if queue is not None:
            await queue.enqueue(FINALIZE_VALIDATION, workspace_id, experiment_id)

    return on_batch_finished
