"""Run counts and last status with manual overrides (008 T034; FR-008, FR-009).

The effective status of a result is the manual verdict when set, else the judge's. Errors are
counted on their own and never as passed or failed. A case's ``last_status`` follows only the
latest run that included it (run ids are ULIDs, so their order is creation order).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass


@dataclass(frozen=True)
class ResultState:
    judge_status: str | None
    override_status: str | None


def effective_status(judge_status: str | None, override_status: str | None) -> str | None:
    return override_status or judge_status


def run_counts(results: Iterable[ResultState]) -> tuple[int, int, int]:
    """(passed, failed, errored) by effective status; unfinished results count nowhere."""
    passed = failed = errored = 0
    for r in results:
        status = effective_status(r.judge_status, r.override_status)
        if status == "passed":
            passed += 1
        elif status == "failed":
            failed += 1
        elif status == "error":
            errored += 1
    return passed, failed, errored


def newer_run(current_last_run_id: str | None, run_id: str) -> bool:
    """Whether ``run_id`` may set a case's last status (it is the case's latest run or newer)."""
    return current_last_run_id is None or run_id >= current_last_run_id
