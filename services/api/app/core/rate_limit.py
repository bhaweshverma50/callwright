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
        return RateLimitResult(
            allowed=int(count) <= limit, count=int(count), limit=limit, retry_after_s=retry_after
        )


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


# Token bucket (010 research R7): ``rate`` tokens per second up to ``burst``. One Lua script
# refills and takes a token atomically; the state is a hash with the token count and the time
# of the last refill.
_BUCKET_SCRIPT = """
local key = KEYS[1]
local rate = tonumber(ARGV[1])
local burst = tonumber(ARGV[2])
local now = tonumber(ARGV[3])
local state = redis.call('HMGET', key, 'tokens', 'ts')
local tokens = tonumber(state[1])
local ts = tonumber(state[2])
if tokens == nil then
  tokens = burst
  ts = now
end
tokens = math.min(burst, tokens + math.max(0, now - ts) * rate)
local allowed = 0
if tokens >= 1 then
  tokens = tokens - 1
  allowed = 1
end
redis.call('HSET', key, 'tokens', tostring(tokens), 'ts', tostring(now))
redis.call('EXPIRE', key, math.ceil(burst / rate) + 1)
return {allowed, tostring(tokens)}
"""


class TokenBucket:
    def __init__(self, redis: Redis, *, rate_per_s: float, burst: int) -> None:
        self.redis = redis
        self.rate = rate_per_s
        self.burst = burst

    async def take(self, bucket: str, key: str, now: float | None = None) -> RateLimitResult:
        """Take one token. ``retry_after_s`` is the whole seconds until one is available."""
        now = time.time() if now is None else now
        allowed, tokens = await self.redis.eval(  # type: ignore[misc]
            _BUCKET_SCRIPT, 1, f"tb:{bucket}:{key}", str(self.rate), str(self.burst), repr(now)
        )
        left = float(tokens)
        wait = 0.0 if int(allowed) else (1.0 - left) / self.rate
        return RateLimitResult(
            allowed=bool(int(allowed)),
            count=self.burst - int(left),
            limit=self.burst,
            retry_after_s=max(1, int(wait + 0.999)),
        )
