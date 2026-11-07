"""Test runs (008)."""

from __future__ import annotations

from app.core.feature import Feature
from app.test_runs.jobs import DISPATCH_TEST_CASE, JUDGE_RESULT, dispatch_test_case, judge_result
from app.test_runs.router import internal_router, router

FEATURE = Feature(
    "test_runs",
    routers=(router, internal_router),
    jobs={DISPATCH_TEST_CASE: dispatch_test_case, JUDGE_RESULT: judge_result},
    id_prefixes=frozenset({"trn"}),
)
