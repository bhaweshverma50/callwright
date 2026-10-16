"""Call and pipeline-step rows, value sets and the guarded state transition (003 T008).

Tables are created by migration s003_0001. ORM mappings declare no foreign keys (the migration
owns them), so the module imports on its own.

State machine (data-model section 1): transitions are applied with
``UPDATE ... WHERE id = :id AND status IN (:expected)``. A stale transition updates nothing and
is logged, never raised, so the first writer wins (disconnect reason included).
"""

from __future__ import annotations

import logging
import math
from collections.abc import Collection
from datetime import datetime
from decimal import Decimal
from typing import Any, Final, Literal

from sqlalchemy import Boolean, DateTime, Integer, Numeric, String, Text, func, update
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

logger = logging.getLogger(__name__)

CallStatus = Literal[
    "queued",
    "ringing",
    "in_progress",
    "ended",
    "processing",
    "completed",
    "failed",
    "no_answer",
    "busy",
    "voicemail",
]
DisconnectReason = Literal[
    "user_hangup",
    "agent_hangup",
    "call_transfer",
    "voicemail_reached",
    "inactivity",
    "max_duration_reached",
    "error",
    "concurrency_limit",
    "insufficient_credit",
]
Channel = Literal["web", "sip_inbound", "sip_outbound", "whatsapp"]
Direction = Literal["inbound", "outbound"]
Origin = Literal["live", "test", "simulation"]

CALL_STATUSES: Final = (
    "queued",
    "ringing",
    "in_progress",
    "ended",
    "processing",
    "completed",
    "failed",
    "no_answer",
    "busy",
    "voicemail",
)
DISCONNECT_REASONS: Final = (
    "user_hangup",
    "agent_hangup",
    "call_transfer",
    "voicemail_reached",
    "inactivity",
    "max_duration_reached",
    "error",
    "concurrency_limit",
    "insufficient_credit",
)
ACTIVE: Final = frozenset({"queued", "ringing", "in_progress"})
NEVER_CONNECTED: Final = frozenset({"failed", "no_answer", "busy"})
# States in which the worker may still post events (``ended`` accepts the final flush).
ACCEPTS_EVENTS: Final = frozenset({"queued", "ringing", "in_progress", "ended"})

# (from, to) pairs allowed by the state machine. ``None`` is "new row".
TRANSITIONS: Final[frozenset[tuple[str | None, str]]] = frozenset(
    {
        (None, "queued"),
        (None, "failed"),
        ("queued", "ringing"),
        ("queued", "in_progress"),
        ("ringing", "in_progress"),
        ("ringing", "no_answer"),
        ("ringing", "busy"),
        ("queued", "failed"),
        ("ringing", "failed"),
        ("in_progress", "ended"),
        ("ended", "processing"),
        ("processing", "completed"),
        ("processing", "voicemail"),
    }
)


def can_transition(current: str | None, new: str) -> bool:
    return (current, new) in TRANSITIONS


def sources_for(new: str) -> tuple[str, ...]:
    """Every status a call may move to ``new`` from (stable order)."""
    return tuple(s for s in CALL_STATUSES if (s, new) in TRANSITIONS)


def billable_seconds(connected_at: datetime | None, ended_at: datetime | None) -> int:
    """Connected time rounded up to the whole second (FR-031); 0 when never connected."""
    if connected_at is None or ended_at is None or ended_at <= connected_at:
        return 0
    return math.ceil((ended_at - connected_at).total_seconds() - 1e-9)


class Call(Base):
    __tablename__ = "calls"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String)
    agent_id: Mapped[str] = mapped_column(String)
    agent_version_id: Mapped[str | None] = mapped_column(String)
    origin: Mapped[str] = mapped_column(String, default="live")
    simulation_run_id: Mapped[str | None] = mapped_column(String)
    channel: Mapped[str] = mapped_column(String)
    direction: Mapped[str] = mapped_column(String)
    from_number: Mapped[str | None] = mapped_column(String)
    to_number: Mapped[str | None] = mapped_column(String)
    phone_number_id: Mapped[str | None] = mapped_column(String)
    whatsapp_channel_id: Mapped[str | None] = mapped_column(String)
    is_test: Mapped[bool] = mapped_column(Boolean, default=False)
    initiated_by_user_id: Mapped[str | None] = mapped_column(String)
    room_name: Mapped[str | None] = mapped_column(String, unique=True)
    sip_call_id: Mapped[str | None] = mapped_column(String)
    status: Mapped[str] = mapped_column(String)
    disconnect_reason: Mapped[str | None] = mapped_column(String)
    diagnostic: Mapped[str | None] = mapped_column(String)
    dynamic_variables: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    missing_variables: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    ignored_overrides: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, default=dict)
    idempotency_key: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ringing_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    connected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    billable_seconds: Mapped[int | None] = mapped_column(Integer)
    usage: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    usage_seq: Mapped[int] = mapped_column(Integer, default=0)
    latency_stats: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    transcript: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    recording_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    recording_setting_source: Mapped[str] = mapped_column(String, default="workspace")
    recording_status: Mapped[str] = mapped_column(String, default="none")
    recording_key: Mapped[str | None] = mapped_column(String)
    egress_id: Mapped[str | None] = mapped_column(String)
    pipeline_status: Mapped[str] = mapped_column(String, default="not_started")
    pipeline_warnings: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    cost_total_usd: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    cost_breakdown: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    summary: Mapped[str | None] = mapped_column(String)
    sentiment: Mapped[str | None] = mapped_column(String)
    analysis: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    worker_job_id: Mapped[str | None] = mapped_column(String)


PipelineStep = Literal[
    "finalize_transcript", "price_and_charge", "analyze", "evaluate", "notify_analyzed", "complete"
]
StepStatus = Literal["pending", "running", "done", "failed", "skipped"]


class CallPipelineStep(Base):
    __tablename__ = "call_pipeline_steps"

    call_id: Mapped[str] = mapped_column(String, primary_key=True)
    step: Mapped[str] = mapped_column(String, primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, default="pending")
    blocking: Mapped[bool] = mapped_column(Boolean)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(String)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


async def transition(
    session: AsyncSession,
    call_id: str,
    expected: str | Collection[str],
    new: str,
    **fields: Any,
) -> bool:
    """Move ``call_id`` to ``new`` when its status is one of ``expected``.

    Returns whether a row changed. Pairs the state machine forbids raise ``ValueError`` (a
    programming error); a call that already moved on is a stale transition and returns False.
    """
    sources = (expected,) if isinstance(expected, str) else tuple(expected)
    for source in sources:
        if not can_transition(source, new):
            raise ValueError(f"forbidden call transition {source} -> {new}")
    values = {"status": new, **fields}
    if "metadata" in values:
        values["metadata_"] = values.pop("metadata")
    result = await session.execute(
        update(Call)
        .where(Call.id == call_id, Call.status.in_(sources))
        .values(**values)
        .returning(Call.id)
        .execution_options(synchronize_session=False)
    )
    changed = result.first() is not None
    if not changed:
        logger.info("stale call transition ignored: %s -> %s for %s", sources, new, call_id)
    return changed
