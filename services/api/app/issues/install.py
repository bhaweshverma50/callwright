"""Wire 009 into the app and the jobs worker: offline fake replies for naming and drafting, the
008 completion hook for validation batches, and the arq jobs and crons."""

from __future__ import annotations

from arq import cron

from app.core.feature import Feature, Runtime
from app.issues import runtime as issues_runtime
from app.issues.jobs import (
    DETECT_ISSUES,
    FINALIZE_VALIDATION,
    audit_applied_issues,
    detect_issues,
    finalize_validation,
    on_batch_finished_factory,
    sweep_issues,
)
from app.issues.router import router
from app.issues.validation import SOURCE
from app.simulator import service as simulator


def install(runtime: Runtime) -> None:
    issues_runtime.register_fakes()
    # Hooks are process-wide; replace ours so repeated installs (tests, reloads) fire once.
    simulator.clear_hooks(SOURCE)
    simulator.on_experiment_finished(SOURCE, on_batch_finished_factory())


FEATURE = Feature(
    "issues",
    routers=(router,),
    install=install,
    jobs={
        DETECT_ISSUES: detect_issues,
        FINALIZE_VALIDATION: finalize_validation,
        "sweep_issues": sweep_issues,
        "audit_applied_issues": audit_applied_issues,
    },
    crons=(
        cron(sweep_issues, second={40}, run_at_startup=False, unique=True),
        cron(audit_applied_issues, hour={5}, minute={30}, run_at_startup=False),
    ),
    id_prefixes=frozenset({"iss"}),
)
