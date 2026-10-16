"""Redis fixed-window rate limiter (T013). Keys: ``rl:{bucket}:{key}:{window_index}``."""

from __future__ import annotations

import time
from dataclasses import dataclass

from redis.asyncio import Redis


@dataclass(frozen=True)
class RateLimitResult:
    allowed: bool
    count: int
    limit: int
    retry_after_s: int


class RateLimiter:
    def __init__(self, redis: Redis) -> None:
        self.redis = redis

    async def hit(self, bucket: str, key: str, *, limit: int, window_s: int) -> RateLimitResult:
        now = time.time()
        window = int(now // window_s)
        redis_key = f"rl:{bucket}:{key}:{window}"
        async with self.redis.pipeline(transaction=True) as pipe:
            pipe.incr(redis_key)
            pipe.expire(redis_key, window_s + 1)
            count, _ = await pipe.execute()
        retry_after = int((window + 1) * window_s - now) + 1
        return RateLimitResult(allowed=int(count) <= limit, count=int(count), limit=limit,
                               retry_after_s=retry_after)


class FailureCounter:
    """Counts failures in a window that starts at the first failure (login throttling, R6)."""

    def __init__(self, redis: Redis) -> None:
        self.redis = redis

    async def count(self, key: str) -> tuple[int, int]:
        """Return (failures, seconds until the window ends)."""
        async with self.redis.pipeline(transaction=True) as pipe:
            pipe.get(key)
            pipe.ttl(key)
            value, ttl = await pipe.execute()
        return (int(value) if value is not None else 0, max(int(ttl), 0))

    async def add(self, key: str, window_s: int) -> int:
        async with self.redis.pipeline(transaction=True) as pipe:
            pipe.incr(key)
            pipe.expire(key, window_s, nx=True)
            count, _ = await pipe.execute()
        return int(count)

    async def clear(self, key: str) -> None:
        await self.redis.delete(key)
