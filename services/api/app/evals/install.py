"""Wire 007 into the app and the jobs worker (T004, T022, T038, T040).

* the quality runtime (``llms`` client, judge, embedder, job queue);
* the 003 pipeline handlers for ``analyze`` and ``evaluate``;
* 006's ``CallQualityPort``;
* the built-in evaluator catalog sync (registry, admin role).
"""

from __future__ import annotations

from typing import Any

from app.core.config import Settings
from app.core.db import Database


def install_handlers() -> None:
    from app.analysis_vars.jobs import pipeline_handler as analyze
    from app.calls.pipeline import register_step_handler
    from app.evals.jobs import pipeline_handler as evaluate

    register_step_handler("analyze", analyze)
    register_step_handler("evaluate", evaluate)


def install_port() -> None:
    from app.calls.quality_port import register_quality_port
    from app.evals.quality_port import QualityPort

    register_quality_port(QualityPort())


async def install(
    settings: Settings, db: Database | None, *, queue: Any = None, llm: Any = None, sync: bool = True
) -> None:
    """The API syncs the built-in catalog at start (``sync``); the jobs worker does not touch the
    database at start-up and relies on the API or the ``migrate`` role having synced it."""
    from app.evals import runtime
    from app.evaluators.registry import sync_builtins

    runtime.install(settings, queue=queue, llm=llm)
    install_handlers()
    install_port()
    if sync and db is not None:
        await sync_builtins(db, settings)


def job_functions() -> list[Any]:
    from app.analysis_vars.jobs import rerun_analysis
    from app.evals.jobs import evaluate_call

    return [rerun_analysis, evaluate_call]
