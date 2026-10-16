"""Jobs to enqueue once a transaction commits.

Services that change call state inside a transaction collect follow-up jobs (pipeline run,
recording start, webhook delivery) in ``Deferred``; the caller enqueues them only after the
commit, so a job never runs against a row that was rolled back.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from app.core.queue import JobQueue

logger = logging.getLogger(__name__)

RUN_PIPELINE = "run_pipeline"
START_RECORDING = "start_recording"
DELIVER_WEBHOOK = "deliver_webhook"


@dataclass(frozen=True)
class Job:
    name: str
    args: tuple[Any, ...]
    defer_by_s: float | None = None
    job_id: str | None = None


@dataclass
class Deferred:
    jobs: list[Job] = field(default_factory=list)

    def add(self, name: str, *args: Any, defer_by_s: float | None = None, job_id: str | None = None) -> None:
        self.jobs.append(Job(name, tuple(args), defer_by_s, job_id))

    def extend(self, other: Deferred) -> None:
        self.jobs.extend(other.jobs)


async def dispatch(queue: JobQueue | None, deferred: Deferred) -> None:
    """Enqueue every collected job. A queue failure is logged: crons and replays recover."""
    if queue is None:
        return
    for job in deferred.jobs:
        try:
            await queue.enqueue(job.name, *job.args, defer_by_s=job.defer_by_s, job_id=job.job_id)
        except Exception:
            logger.exception("could not enqueue %s%s", job.name, job.args)
    deferred.jobs.clear()
