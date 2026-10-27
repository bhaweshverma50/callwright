"""Call embeddings for ``anomaly_detection`` (007 T082, research R13, FR-042).

A call is embedded from a normalised text (agent and caller lines, tool names, end reason)
through 005's embedding adapter. Live calls are stored in ``call_embeddings``; neighbours are the
``knn_k`` nearest stored calls of the same agent that ended within ``window_days``, excluding the
call itself, by pgvector cosine distance. When fewer than ``min_sample_size`` exist, up to
``backfill_per_run`` completed live calls of the agent without an embedding are embedded first.
Embedding work is recorded as ``embedding`` usage with a zero billable amount: the check is free.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing import service as billing
from app.calls.models import Call
from app.evals.context import parse_transcript
from app.evaluators.base import EvalContext, Message, ToolEvent

MAX_CHARS = 8000
# Embedding list price per million tokens (005 adapters use text-embedding-3-small class models).
EMBED_USD_PER_MTOK = Decimal("0.02")


@dataclass(frozen=True)
class Neighbours:
    distances: list[float]
    comparable: int


def call_text(messages: Sequence[Message], tools: Sequence[ToolEvent], end_reason: str | None) -> str:
    lines = [f"{'agent' if m.role == 'agent' else 'caller'}: {' '.join(m.text.split())}" for m in messages]
    if tools:
        lines.append("tools: " + ", ".join(t.name for t in tools))
    lines.append(f"ended: {end_reason or 'unknown'}")
    return "\n".join(lines)[:MAX_CHARS]


def _literal(vector: Sequence[float]) -> str:
    return "[" + ",".join(f"{v:.7f}" for v in vector) + "]"


async def _record_usage(
    session: AsyncSession, workspace_id: str, call_id: str, source: str, embedder: Any
) -> None:
    tokens = max(1, len(source) // 4)
    raw = (Decimal(tokens) * EMBED_USD_PER_MTOK / Decimal(1_000_000)).quantize(Decimal("0.000001"))
    if getattr(embedder, "provider", "") == "fake":
        raw = Decimal(0)
    await billing.charge_feature(
        session,
        workspace_id=workspace_id,
        feature_key="embedding",
        quantity=Decimal(tokens),
        unit="tokens",
        raw_cost_usd=raw,
        billable_cost_usd=Decimal(0),
        idempotency_key=f"call_embedding:{call_id}:{hashlib.sha256(source.encode()).hexdigest()[:16]}",
        ref_type="call",
        ref_id=call_id,
    )


async def store(
    session: AsyncSession,
    embedder: Any,
    *,
    workspace_id: str,
    call_id: str,
    agent_id: str,
    ended_at: datetime,
    source: str,
) -> list[float]:
    digest = hashlib.sha256(source.encode()).hexdigest()
    existing = (
        await session.execute(
            text("select source_sha256, embedding::text from call_embeddings where call_id = :id"),
            {"id": call_id},
        )
    ).first()
    if existing is not None and existing[0] == digest:
        return [float(x) for x in existing[1].strip("[]").split(",")]
    vector = (await embedder.embed([source]))[0]
    await session.execute(
        text(
            "insert into call_embeddings (call_id, workspace_id, agent_id, ended_at, embedding, model, source_sha256) "
            "values (:id, :ws, :agent, :ended, cast(:vec as vector), :model, :sha) "
            "on conflict (call_id) do update set embedding = excluded.embedding, model = excluded.model, "
            "source_sha256 = excluded.source_sha256, ended_at = excluded.ended_at"
        ),
        {
            "id": call_id,
            "ws": workspace_id,
            "agent": agent_id,
            "ended": ended_at,
            "vec": _literal(vector),
            "model": f"{embedder.provider}/{embedder.model}",
            "sha": digest,
        },
    )
    await _record_usage(session, workspace_id, call_id, source, embedder)
    return list(vector)


async def _count(session: AsyncSession, ctx: EvalContext, since: datetime) -> int:
    return int(
        (
            await session.execute(
                text(
                    "select count(*) from call_embeddings where agent_id = :agent and call_id <> :id "
                    "and ended_at >= :since"
                ),
                {"agent": ctx.agent_id, "id": ctx.call_id, "since": since},
            )
        ).scalar_one()
    )


async def backfill(
    session: AsyncSession, embedder: Any, ctx: EvalContext, since: datetime, limit: int
) -> int:
    if limit <= 0:
        return 0
    rows = (
        await session.execute(
            text(
                "select c.id from calls c left join call_embeddings e on e.call_id = c.id "
                "where c.agent_id = :agent and c.origin = 'live' and c.status in ('completed', 'voicemail') "
                "and c.ended_at >= :since and c.id <> :id and e.call_id is null "
                "order by c.ended_at desc limit :n"
            ),
            {"agent": ctx.agent_id, "since": since, "id": ctx.call_id, "n": limit},
        )
    ).scalars()
    done = 0
    for call_id in list(rows):
        call = await session.get(Call, call_id)
        if call is None or call.ended_at is None:
            continue
        messages, tools, _ = parse_transcript(list((call.transcript or {}).get("items") or []))
        if not messages:
            continue
        await store(
            session,
            embedder,
            workspace_id=call.workspace_id,
            call_id=call.id,
            agent_id=call.agent_id,
            ended_at=call.ended_at,
            source=call_text(messages, tools, call.disconnect_reason),
        )
        done += 1
    return done


async def neighbours(
    session: AsyncSession, embedder: Any, ctx: EvalContext, settings: Mapping[str, Any]
) -> Neighbours:
    ended = ctx.ended_at
    if ended is None:
        return Neighbours([], 0)
    source = call_text(ctx.messages, ctx.tools, ctx.disconnect_reason)
    if ctx.origin == "live":
        vector = await store(
            session,
            embedder,
            workspace_id=ctx.workspace_id,
            call_id=ctx.call_id,
            agent_id=ctx.agent_id,
            ended_at=ended,
            source=source,
        )
    else:
        vector = list((await embedder.embed([source]))[0])
    since = ended - timedelta(days=int(settings["window_days"]))
    comparable = await _count(session, ctx, since)
    if comparable < int(settings["min_sample_size"]):
        await backfill(session, embedder, ctx, since, int(settings["backfill_per_run"]))
        comparable = await _count(session, ctx, since)
    rows = (
        await session.execute(
            text(
                "select (embedding <=> cast(:vec as vector)) as d from call_embeddings "
                "where agent_id = :agent and call_id <> :id and ended_at >= :since "
                "order by embedding <=> cast(:vec as vector) limit :k"
            ),
            {
                "vec": _literal(vector),
                "agent": ctx.agent_id,
                "id": ctx.call_id,
                "since": since,
                "k": int(settings["knn_k"]),
            },
        )
    ).scalars()
    return Neighbours([float(d) for d in rows], comparable)
