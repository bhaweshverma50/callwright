"""``Idempotency-Key`` storage and replay (003 T011, data-model section 8).

POSTs that spend credit or place calls take a client key (8 to 255 characters). The first request
with a key claims a row in ``idempotency_keys`` (keyed by workspace, endpoint and key) before
any work; its final response, success or problem, is stored and replayed verbatim for 24 hours.

* Same key, different body: 422 ``idempotency_key_reused``.
* Same key while the first request is still running: 409 ``idempotency_key_in_use``. A claim
  left behind by a crashed request is taken over after ``STALE_AFTER_S``.
* An unexpected exception releases the claim, so the client can retry with the same key.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any

from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.core.db import Database
from app.core.errors import PROBLEM_JSON, ProblemError

STALE_AFTER_S = 120
MIN_KEY_LENGTH = 8
MAX_KEY_LENGTH = 255


@dataclass(frozen=True)
class StoredResponse:
    status: int
    body: Any
    problem: bool


def request_hash(body: Any) -> str:
    """SHA-256 of the canonical JSON form of the request body."""
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


def require_key(key: str | None) -> str:
    if key is None or not (MIN_KEY_LENGTH <= len(key.strip()) <= MAX_KEY_LENGTH):
        raise ProblemError(
            400,
            "idempotency_key_required",
            "Idempotency key required",
            f"Send an Idempotency-Key header of {MIN_KEY_LENGTH} to {MAX_KEY_LENGTH} characters.",
        )
    return key.strip()


async def claim(db: Database, workspace_id: str, endpoint: str, key: str, body: Any) -> StoredResponse | None:
    """Claim ``key`` for this request. Returns the stored response to replay, or None to proceed."""
    digest = request_hash(body)
    params = {"ws": workspace_id, "ep": endpoint, "key": key, "hash": digest, "stale": STALE_AFTER_S}
    async with db.transaction(workspace_id=workspace_id) as session:
        await session.execute(
            text(
                "delete from idempotency_keys where workspace_id = :ws and endpoint = :ep "
                "and key = :key and expires_at < now()"
            ),
            params,
        )
        inserted = (
            await session.execute(
                text(
                    "insert into idempotency_keys (workspace_id, endpoint, key, request_hash) "
                    "values (:ws, :ep, :key, :hash) on conflict do nothing returning key"
                ),
                params,
            )
        ).first()
        if inserted is not None:
            return None
        row = (
            await session.execute(
                text(
                    "select request_hash, response_status, response_body, "
                    "created_at < now() - make_interval(secs => :stale) as stale "
                    "from idempotency_keys where workspace_id = :ws and endpoint = :ep and key = :key "
                    "for update"
                ),
                params,
            )
        ).one()
        if row.request_hash != digest:
            raise ProblemError(
                422,
                "idempotency_key_reused",
                "Idempotency key reused",
                "This Idempotency-Key was already used with a different request body.",
            )
        if row.response_status is None:
            if not row.stale:
                raise ProblemError(
                    409,
                    "idempotency_key_in_use",
                    "Request in progress",
                    "A request with this Idempotency-Key is still being processed.",
                )
            await session.execute(
                text(
                    "update idempotency_keys set created_at = now() "
                    "where workspace_id = :ws and endpoint = :ep and key = :key"
                ),
                params,
            )
            return None
        stored: Mapping[str, Any] = row.response_body or {}
        return StoredResponse(
            status=int(row.response_status), body=stored.get("body"), problem=bool(stored.get("problem"))
        )


async def store(
    db: Database, workspace_id: str, endpoint: str, key: str, status: int, body: Any, *, problem: bool
) -> None:
    async with db.transaction(workspace_id=workspace_id) as session:
        await session.execute(
            text(
                "update idempotency_keys set response_status = :status, "
                "response_body = cast(:body as jsonb) "
                "where workspace_id = :ws and endpoint = :ep and key = :key"
            ),
            {
                "ws": workspace_id,
                "ep": endpoint,
                "key": key,
                "status": status,
                "body": json.dumps({"body": body, "problem": problem}, default=str),
            },
        )


async def release(db: Database, workspace_id: str, endpoint: str, key: str) -> None:
    async with db.transaction(workspace_id=workspace_id) as session:
        await session.execute(
            text(
                "delete from idempotency_keys where workspace_id = :ws and endpoint = :ep "
                "and key = :key and response_status is null"
            ),
            {"ws": workspace_id, "ep": endpoint, "key": key},
        )


def replay_response(stored: StoredResponse) -> JSONResponse:
    media_type = PROBLEM_JSON if stored.problem else "application/json"
    return JSONResponse(stored.body, status_code=stored.status, media_type=media_type)


Handler = Callable[[], Awaitable[tuple[int, Any]]]


async def run_idempotent(
    db: Database,
    *,
    workspace_id: str,
    endpoint: str,
    key: str,
    body: Any,
    handler: Handler,
    instance: str | None = None,
) -> JSONResponse:
    """Run ``handler`` at most once per key; replay the stored response afterwards.

    ``handler`` returns ``(status, json_body)``. A ``ProblemError`` it raises is stored and
    re-raised (so refusals replay as the same problem); any other exception releases the key.
    """
    stored = await claim(db, workspace_id, endpoint, key, body)
    if stored is not None:
        return replay_response(stored)
    try:
        status, result = await handler()
    except ProblemError as problem:
        await store(db, workspace_id, endpoint, key, problem.status, problem.body(instance), problem=True)
        raise
    except BaseException:
        await release(db, workspace_id, endpoint, key)
        raise
    await store(db, workspace_id, endpoint, key, status, result, problem=False)
    return JSONResponse(result, status_code=status)
