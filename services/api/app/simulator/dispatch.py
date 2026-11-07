"""Text-runner dispatch: the ``textsim`` queue and the per-workspace semaphore (008 T013; R11).

The voice-worker's ``textsim`` role consumes the arq queue ``arq:textsim`` with two jobs:
``run_single_turn(test_run_id, test_case_id)`` and ``run_simulation(simulation_run_id)``. Jobs on
the API's own queue (``simulator.jobs``) gate them: a slot in the workspace's semaphore
(``sim:sem:{workspace_id}``, a sorted set of holders scored by acquisition time, limit
``SIM_MAX_CONCURRENCY``, default 10) is taken before enqueueing, and released when the runner
posts its result, the work is cancelled or the sweeper fails it. A holder older than
``SLOT_TTL_S`` is dropped, so a crashed runner cannot hold a slot for ever. A job that finds no
free slot re-enqueues itself after ``RETRY_DEFER_S``.
"""

from __future__ import annotations

import time
from typing import Any, Protocol

from callwright_contract.values import TEXTSIM_QUEUE

RETRY_DEFER_S = 5.0
SLOT_TTL_S = 20 * 60

_ACQUIRE = """
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', ARGV[1])
if redis.call('ZSCORE', KEYS[1], ARGV[3]) then return 1 end
if redis.call('ZCARD', KEYS[1]) < tonumber(ARGV[2]) then
  redis.call('ZADD', KEYS[1], ARGV[4], ARGV[3])
  redis.call('EXPIRE', KEYS[1], ARGV[5])
  return 1
end
return 0
"""


def semaphore_key(workspace_id: str) -> str:
    return f"sim:sem:{workspace_id}"


async def acquire(
    redis: Any, workspace_id: str, holder: str, limit: int, *, now: float | None = None
) -> bool:
    """Take one of ``limit`` slots for ``holder`` (idempotent per holder)."""
    stamp = time.time() if now is None else now
    result = await redis.eval(
        _ACQUIRE,
        1,
        semaphore_key(workspace_id),
        stamp - SLOT_TTL_S,
        limit,
        holder,
        stamp,
        SLOT_TTL_S * 2,
    )
    return bool(int(result))


async def release(redis: Any, workspace_id: str, holder: str) -> None:
    await redis.zrem(semaphore_key(workspace_id), holder)


async def holders(redis: Any, workspace_id: str) -> list[str]:
    raw = await redis.zrange(semaphore_key(workspace_id), 0, -1)
    return [h.decode() if isinstance(h, bytes) else str(h) for h in raw]


class TextsimQueue(Protocol):
    async def enqueue(self, name: str, *args: Any, job_id: str | None = None) -> None: ...


class ArqTextsimQueue:
    """Enqueue onto ``arq:textsim`` through an arq pool (the jobs worker's ``ctx["redis"]``)."""

    def __init__(self, pool: Any) -> None:
        self.pool = pool

    async def enqueue(self, name: str, *args: Any, job_id: str | None = None) -> None:
        await self.pool.enqueue_job(name, *args, _job_id=job_id, _queue_name=TEXTSIM_QUEUE)


def textsim_queue(ctx: dict[str, Any]) -> TextsimQueue:
    queue = ctx.get("textsim")
    if queue is None:
        queue = ArqTextsimQueue(ctx["redis"])
        ctx["textsim"] = queue
    return queue
