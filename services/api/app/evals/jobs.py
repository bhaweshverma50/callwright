"""Evaluation jobs (007 T038): the 003 ``evaluate`` step and the ``evaluate_call`` arq job.

The pipeline step creates the call's ``pipeline`` run group in the step's transaction and
enqueues ``evaluate_call`` once that transaction commits, so the slow evaluator work never holds
the call row. Reruns (API) and 008's dataset and simulation runs create their group with
``runner.start_group`` and enqueue ``evaluate_call`` after their transaction commits.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.calls.models import Call
from app.calls.pipeline import step_deferred
from app.core.db import Database
from app.evals.runner import AlreadyRunning, execute_group, start_group

logger = logging.getLogger(__name__)
EVALUATE_CALL = "evaluate_call"


async def pipeline_handler(call_id: str, session: AsyncSession) -> None:
    call = await session.get(Call, call_id)
    if call is None:
        return
    try:
        start = await start_group(session, call, trigger="pipeline", idempotency_key="pipeline")
    except AlreadyRunning:
        logger.info("checks already running for %s; pipeline evaluation skipped", call_id)
        return
    if start.group.status != "active":
        return
    deferred = step_deferred()
    job = (call.workspace_id, call_id, start.group.run_group_id)
    if deferred is None:
        raise RuntimeError("the evaluate step runs inside a pipeline step")
    deferred.add(EVALUATE_CALL, *job, job_id=f"evaluate:{start.group.run_group_id}")


async def evaluate_call(ctx: dict[str, Any], workspace_id: str, call_id: str, run_group_id: str) -> str:
    db: Database = ctx["db"]
    return await execute_group(db, workspace_id, run_group_id)
