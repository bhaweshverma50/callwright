"""Wire 009 into the app and the jobs worker: the issues runtime (model client, embedder and
offline fakes), the 008 completion hook for validation batches, and the arq jobs and crons."""

from __future__ import annotations

from typing import Any

from arq import cron
from arq.cron import CronJob

from app.core.config import Settings


def install(settings: Settings | None = None) -> None:
    from app.issues import runtime
    from app.issues.jobs import on_batch_finished_factory
    from app.issues.validation import SOURCE
    from app.simulator import service as simulator

    runtime.install(settings)
    # Hooks are process-wide; replace ours so repeated installs (tests, reloads) fire once.
    simulator.clear_hooks(SOURCE)
    simulator.on_experiment_finished(SOURCE, on_batch_finished_factory())


def job_functions() -> list[Any]:
    from app.issues.jobs import audit_applied_issues, detect_issues, finalize_validation, sweep_issues

    return [detect_issues, finalize_validation, sweep_issues, audit_applied_issues]


def crons() -> list[CronJob]:
    from app.issues.jobs import audit_applied_issues, sweep_issues

    return [
        cron(sweep_issues, second={40}, run_at_startup=False, unique=True),
        cron(audit_applied_issues, hour={5}, minute={30}, run_at_startup=False),
    ]
