"""Test runs (008): the run jobs, the sweeper and offline fake replies for the judge."""

from __future__ import annotations

from arq import cron

from app.core.feature import Feature, Runtime
from app.test_runs import judge
from app.test_runs.jobs import (
    DISPATCH_TEST_CASE,
    JUDGE_RESULT,
    SWEEP_TEST_RESULTS,
    dispatch_test_case,
    judge_result,
    sweep_test_results,
)
from app.test_runs.router import internal_router, router


def install(runtime: Runtime) -> None:
    judge.register_fakes()


FEATURE = Feature(
    "test_runs",
    routers=(router, internal_router),
    install=install,
    jobs={
        DISPATCH_TEST_CASE: dispatch_test_case,
        JUDGE_RESULT: judge_result,
        SWEEP_TEST_RESULTS: sweep_test_results,
    },
    crons=(cron(sweep_test_results, second={20}, run_at_startup=False, unique=True),),
    id_prefixes=frozenset({"trn"}),
)
