"""The worker protocol: dispatch metadata, the claim (``POST /v1/internal/calls/claim``), the
event batch (``POST /v1/internal/calls/{call_id}/events``), as in
``specs/003-voice-runtime/contracts/calls.yaml`` and ``call_events.yaml``, and the bodies of the
internal routes the worker's tools call during a call (005 tool secrets and knowledge search,
011 callbacks, 012 language switches).

The claim's ``runtime`` carries every value the worker needs fully resolved by the API, which
owns the catalogs and defaults: the version config with call-behaviour defaults applied, the call
limits, the control range table, the speech recognition Auto table and the model Auto picked for
the call. The worker keeps no defaults or tables of its own. The text runner (008) receives the
same :class:`RuntimeValues` in its run specs.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from callwright_contract.calls import (
    AgentType,
    Channel,
    ControlReason,
    Direction,
    DisconnectReason,
    RefusalReason,
    WorkerStatus,
)
from callwright_contract.values import (
    CALLBACK_MAX_IN_MINUTES,
    CALLBACK_MAX_NOTE_CHARS,
    DTMF_EVENT_DIGITS_PATTERN,
)

# Dispatch metadata keys: ``{"call_id"}`` for calls the API created (web, outbound), or
# ``{"channel", "route_ref"}`` for inbound SIP and WhatsApp calls routed at claim (010).
DISPATCH_CALL_ID: Final = "call_id"
DISPATCH_CHANNEL: Final = "channel"
DISPATCH_ROUTE_REF: Final = "route_ref"

MAX_EVENTS_PER_BATCH: Final = 200
MAX_TOOL_OUTPUT_CHARS: Final = 8192
MAX_DETAIL_CHARS: Final = 2000
MAX_DIAGNOSTIC_CHARS: Final = 500


class SipAttributes(BaseModel):
    model_config = ConfigDict(extra="allow")

    call_id: str | None = None
    trunk_id: str | None = None
    trunk_phone_number: str | None = None
    caller_number: str | None = None
    participant_identity: str | None = None


class ClaimRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str = Field(min_length=1, max_length=200)
    room_name: str = Field(min_length=1, max_length=200)
    worker_id: str = Field(min_length=1, max_length=200)
    dispatch_metadata: dict[str, Any]
    sip: SipAttributes | None = None


class Refusal(BaseModel):
    disconnect_reason: RefusalReason
    diagnostic: str | None = None


class Limits(BaseModel):
    end_on_silence_s: int
    max_duration_s: int
    ring_duration_ms: int


class OutboundDial(BaseModel):
    sip_trunk_id: str
    to_number: str
    from_number: str
    ring_timeout_s: int


class ControlRange(BaseModel):
    """One row of 002's control range table (data-model 8.6); ``path`` is a JSON Pointer into
    the agent config (``/tts/speed``)."""

    model_config = ConfigDict(extra="ignore")

    path: str
    min: float
    max: float
    step: float | None = None


class SttAuto(BaseModel):
    """How speech recognition Auto picks a model for one provider (002 data-model 8.3): the
    language code exactly, then its base (``en-US`` -> ``en``), then the default; a model that
    does not list the language counts as none."""

    default: str | None = None
    by_language: dict[str, str] = Field(default_factory=dict)
    languages: dict[str, list[str]] = Field(default_factory=dict)

    def pick(self, language: str) -> str | None:
        """The rule alone, as the agent builder shows it."""
        return self.by_language.get(language) or self.by_language.get(language.split("-")[0]) or self.default

    def resolve(self, language: str) -> str | None:
        """The model a call in ``language`` runs, or None when no model covers it."""
        model = self.pick(language)
        return model if model is not None and language in self.languages.get(model, ()) else None


class LanguageOption(BaseModel):
    """One language the caller can switch to (012); the agent's own language comes first."""

    model_config = ConfigDict(extra="ignore")

    code: str
    label: str
    stt_model: str | None = None
    tts_model: str | None = None


class RuntimeValues(BaseModel):
    """What the API resolves from a version config for any run of it (call or text run)."""

    model_config = ConfigDict(extra="ignore")

    config: dict[str, Any]
    limits: Limits
    controls: list[ControlRange]
    stt_auto_rules: dict[str, SttAuto]
    stt_resolved_model: str | None = None
    language_options: list[LanguageOption] = Field(default_factory=list)

    def control(self, path: str) -> ControlRange | None:
        return next((c for c in self.controls if c.path == path), None)


class RuntimeConfig(RuntimeValues):
    """Frozen configuration for one call (contract ``RuntimeConfig``). Unknown keys are kept: the
    offline harness passes its stubs this way."""

    model_config = ConfigDict(extra="allow")

    channel: Channel
    direction: Direction
    from_number: str | None = None
    to_number: str | None = None
    agent_id: str
    agent_version_id: str
    agent_type: AgentType
    variables: dict[str, str] = Field(default_factory=dict)
    background_audio_url: str | None = None
    caller_join_timeout_s: int = 60
    outbound_dial: OutboundDial | None = None
    heartbeat_interval_s: int = 10
    recording_enabled: bool | None = None
    # 012: the phone caller's saved language.
    caller_language: str | None = None
    # 008 text runs and the offline harness: tools answer without side effects.
    simulation: bool = False


class ClaimResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    admitted: bool
    call_id: str
    refusal: Refusal | None = None
    runtime: RuntimeConfig | None = None


class _Event(BaseModel):
    model_config = ConfigDict(extra="allow")

    seq: int = Field(ge=1)
    occurred_at: datetime
    offset_ms: int | None = None


class StatusEvent(_Event):
    type: Literal["status"]
    status: WorkerStatus
    disconnect_reason: DisconnectReason | None = None
    diagnostic: str | None = Field(default=None, max_length=MAX_DIAGNOSTIC_CHARS)
    sip_status_code: int | None = None


class TurnEvent(_Event):
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
    """One transcript entry. ``message``: role, text, started_ms, ended_ms, turn_index,
    interrupted, confidence, source; ``tool_call``/``tool_result``: name, ref, arguments, output,
    is_error, duration_ms, answer_source; ``flow_transition``: to_node_id, from_node_id, label;
    ``system``: event, detail. Timed items without their own span carry ``at_ms``."""

    model_config = ConfigDict(extra="allow")

    type: Literal["message", "tool_call", "tool_result", "flow_transition", "system"]
    output: str | None = Field(default=None, max_length=MAX_TOOL_OUTPUT_CHARS)
    detail: str | None = Field(default=None, max_length=MAX_DETAIL_CHARS)
    confidence: float | None = Field(default=None, ge=0, le=1)


class TranscriptItemEvent(_Event):
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


class UsageEvent(_Event):
    type: Literal["usage"]
    usage: UsageSnapshot


class ToolCallEvent(_Event):
    type: Literal["tool_call"]
    name: str
    ref: str | None = None
    arguments: dict[str, Any] | None = None
    output: str | None = Field(default=None, max_length=MAX_TOOL_OUTPUT_CHARS)
    is_error: bool | None = None
    duration_ms: int | None = None


class FlowTransitionEvent(_Event):
    type: Literal["flow_transition"]
    to_node_id: str
    from_node_id: str | None = None
    label: str | None = None


class DtmfEvent(_Event):
    type: Literal["dtmf"]
    digits: str = Field(pattern=DTMF_EVENT_DIGITS_PATTERN)
    direction: Literal["received", "sent"]
    flush_reason: Literal["termination_key", "digit_limit", "timeout"] | None = None


class WarningEvent(_Event):
    type: Literal["warning", "error"]
    code: str
    component: Literal["stt", "llm", "tts", "nc", "vad", "runtime", "recording"] | None = None
    provider: str | None = None
    detail: str | None = Field(default=None, max_length=MAX_DETAIL_CHARS)


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
    events: list[CallEventIn] = Field(default_factory=list, max_length=MAX_EVENTS_PER_BATCH)


class Control(BaseModel):
    """``end_call`` orders the worker to hang up (mid-call credit guard, FR-025)."""

    action: Literal["none", "end_call"] = "none"
    disconnect_reason: ControlReason | None = None


class EventBatchResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    accepted: int
    duplicates: int
    control: Control = Field(default_factory=Control)


MAX_KNOWLEDGE_BASES: Final = 10
KB_QUERY_MAX_CHARS: Final = 1000
KB_DEFAULT_TOP_K: Final = 4
KB_MAX_TOP_K: Final = 8


class KbSearchRequest(BaseModel):
    """``POST /v1/internal/knowledge/search``: the knowledge bases must belong to the version the
    call runs. ``call_id`` is a test run id for 008's single-turn test cases (no call exists)."""

    model_config = ConfigDict(extra="forbid")

    call_id: str = Field(pattern=r"^(call|trn)_")
    query: str = Field(min_length=1, max_length=KB_QUERY_MAX_CHARS)
    kb_ids: list[Annotated[str, Field(pattern=r"^kb_")]] = Field(min_length=1, max_length=MAX_KNOWLEDGE_BASES)
    top_k: int = Field(default=KB_DEFAULT_TOP_K, ge=1, le=KB_MAX_TOP_K)


class CallbackRequest(BaseModel):
    """``POST /v1/internal/calls/{call_id}/callbacks`` (011): a local time or minutes from now."""

    model_config = ConfigDict(extra="forbid")

    at: str | None = Field(default=None, max_length=40)
    in_minutes: int | None = Field(default=None, ge=1, le=CALLBACK_MAX_IN_MINUTES)
    note: str = Field(default="", max_length=CALLBACK_MAX_NOTE_CHARS)

    @model_validator(mode="after")
    def _one_time(self) -> CallbackRequest:
        if (self.at is None) == (self.in_minutes is None):
            raise ValueError("Give exactly one of at and in_minutes.")
        return self


class LanguageReport(BaseModel):
    """``POST /v1/internal/calls/{call_id}/language`` (012): the caller's language changed."""

    model_config = ConfigDict(extra="forbid")

    language: str = Field(min_length=2, max_length=16)
    offset_ms: int | None = Field(default=None, ge=0)


class ToolSecrets(BaseModel):
    """``GET /v1/internal/calls/{call_id}/tool-secrets`` (005): plaintext by ``secret_ref``."""

    secrets: dict[str, str] = Field(default_factory=dict)
