"""Event batch schemas (contracts/call_events.yaml, 003 T033).

Shapes match what the worker's ``EventRecorder`` (``services/voice-worker/worker/metrics.py``)
emits; the contract test drives the real worker client against this API. Unknown extra fields
are kept in ``payload`` so a newer worker never loses data on an older API.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

DisconnectReasonIn = Literal[
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


class _Base(BaseModel):
    model_config = ConfigDict(extra="allow")

    seq: int = Field(ge=1)
    occurred_at: datetime
    offset_ms: int | None = None


class StatusEvent(_Base):
    type: Literal["status"]
    status: Literal["ringing", "in_progress", "ended", "no_answer", "busy", "failed"]
    disconnect_reason: DisconnectReasonIn | None = None
    diagnostic: str | None = Field(default=None, max_length=500)
    sip_status_code: int | None = None


class TurnEvent(_Base):
    type: Literal["turn"]
    turn_index: int = Field(ge=0)
    stt_final_ms: int | None = None
    eou_delay_ms: int | None = None
    llm_ttft_ms: int | None = None
    tts_ttfb_ms: int | None = None
    e2e_ms: int | None = None
    tool_ms: int | None = None
    interrupted: bool | None = None


class TranscriptItem(BaseModel):
    model_config = ConfigDict(extra="allow")

    type: Literal["message", "tool_call", "tool_result", "flow_transition", "system"]
    output: str | None = Field(default=None, max_length=8192)
    confidence: float | None = Field(default=None, ge=0, le=1)


class TranscriptItemEvent(_Base):
    type: Literal["transcript_item"]
    item: TranscriptItem


class SttMeter(BaseModel):
    model_config = ConfigDict(extra="allow")
    provider: str
    model: str
    audio_ms: int = Field(ge=0)


class LlmMeter(BaseModel):
    model_config = ConfigDict(extra="allow")
    provider: str
    model: str
    input_tokens: int = Field(ge=0)
    cached_input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(ge=0)


class TtsMeter(BaseModel):
    model_config = ConfigDict(extra="allow")
    provider: str
    model: str | None = None
    characters: int = Field(ge=0)


class NcMeter(BaseModel):
    model_config = ConfigDict(extra="allow")
    provider: str
    model: str | None = None
    audio_ms: int = Field(ge=0)


class UsageSnapshot(BaseModel):
    model_config = ConfigDict(extra="allow")
    stt: list[SttMeter] = Field(default_factory=list)
    llm: list[LlmMeter] = Field(default_factory=list)
    tts: list[TtsMeter] = Field(default_factory=list)
    nc: list[NcMeter] = Field(default_factory=list)


class UsageEvent(_Base):
    type: Literal["usage"]
    usage: UsageSnapshot


class ToolCallEvent(_Base):
    type: Literal["tool_call"]
    name: str
    ref: str | None = None
    arguments: dict[str, Any] | None = None
    output: str | None = Field(default=None, max_length=8192)
    is_error: bool | None = None
    duration_ms: int | None = None


class FlowTransitionEvent(_Base):
    type: Literal["flow_transition"]
    to_node_id: str
    from_node_id: str | None = None
    label: str | None = None


class DtmfEvent(_Base):
    type: Literal["dtmf"]
    digits: str = Field(pattern=r"^[0-9*#]{1,99}$")
    direction: Literal["received", "sent"]
    flush_reason: Literal["termination_key", "digit_limit", "timeout"] | None = None


class WarningEvent(_Base):
    type: Literal["warning", "error"]
    code: str
    component: Literal["stt", "llm", "tts", "nc", "vad", "runtime", "recording"] | None = None
    provider: str | None = None
    detail: str | None = Field(default=None, max_length=2000)


CallEventIn = Annotated[
    StatusEvent
    | TurnEvent
    | TranscriptItemEvent
    | UsageEvent
    | ToolCallEvent
    | FlowTransitionEvent
    | DtmfEvent
    | WarningEvent,
    Field(discriminator="type"),
]


class EventBatch(BaseModel):
    events: list[CallEventIn] = Field(default_factory=list, max_length=200)


class Control(BaseModel):
    action: Literal["none", "end_call"] = "none"
    disconnect_reason: Literal["insufficient_credit", "error"] | None = None


class EventBatchResult(BaseModel):
    accepted: int
    duplicates: int
    control: Control
