"""Double-submit protection for agent create and duplicate (T098, FR-038).

Redis key ``idem:agents:{workspace_id}:{key}`` (24 h) holds the id of the agent the first request
created. A concurrent request with the same key waits briefly for the first to finish, then
returns the same agent, so one user action creates exactly one agent.
"""

from __future__ import annotations

import asyncio

from redis.asyncio import Redis

from app.core.errors import ProblemError

TTL_S = 24 * 3600
PENDING = "pending"
PENDING_TTL_S = 30
WAIT_STEP_S = 0.1
WAIT_STEPS = 100


class AgentIdempotency:
    def __init__(self, redis: Redis, workspace_id: str, key: str) -> None:
        self.redis = redis
        self.key = f"idem:agents:{workspace_id}:{key}"

    async def claim_or_existing(self) -> str | None:
        """``None`` when this request owns the key; otherwise the agent id created earlier."""
        for _ in range(WAIT_STEPS):
            value = await self.redis.get(self.key)
            if value is None:
                if await self.redis.set(self.key, PENDING, ex=PENDING_TTL_S, nx=True):
                    return None
                continue
            text = value.decode() if isinstance(value, bytes) else str(value)
            if text != PENDING:
                return text
            await asyncio.sleep(WAIT_STEP_S)
        raise ProblemError(
            409, "request_in_progress", "Request in progress", "The same request is still being processed."
        )

    async def complete(self, agent_id: str) -> None:
        await self.redis.set(self.key, agent_id, ex=TTL_S)

    async def release(self) -> None:
        await self.redis.delete(self.key)
