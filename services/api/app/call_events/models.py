"""Runtime events posted by the voice worker (003 T009, data-model section 2).

Ordered and de-duplicated per call by ``(call_id, seq)``; rows are inserted with
``ON CONFLICT DO NOTHING`` so worker retries are harmless. Heartbeats are not stored.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, Boolean, DateTime, Identity, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

EVENT_TYPES = (
    "status",
    "turn",
    "transcript_item",
    "usage",
    "tool_call",
    "flow_transition",
    "dtmf",
    "warning",
    "error",
)


class CallEvent(Base):
    __tablename__ = "call_events"
    __table_args__ = (UniqueConstraint("call_id", "seq"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String)
    call_id: Mapped[str] = mapped_column(String)
    seq: Mapped[int] = mapped_column(Integer)
    type: Mapped[str] = mapped_column(String)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    offset_ms: Mapped[int | None] = mapped_column(Integer)
    turn_index: Mapped[int | None] = mapped_column(Integer)
    stt_final_ms: Mapped[int | None] = mapped_column(Integer)
    eou_delay_ms: Mapped[int | None] = mapped_column(Integer)
    llm_ttft_ms: Mapped[int | None] = mapped_column(Integer)
    tts_ttfb_ms: Mapped[int | None] = mapped_column(Integer)
    e2e_ms: Mapped[int | None] = mapped_column(Integer)
    tool_ms: Mapped[int | None] = mapped_column(Integer)
    interrupted: Mapped[bool | None] = mapped_column(Boolean)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
