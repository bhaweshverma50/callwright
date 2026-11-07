"""Call vocabulary (003 data-model section 1). Migrations keep their own literal CHECK lists; the
API's ``tests/integration/test_contract_vocabulary.py`` keeps them equal to these."""

from __future__ import annotations

from typing import Final, Literal, get_args

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
CALL_STATUSES: Final[tuple[CallStatus, ...]] = get_args(CallStatus)
ACTIVE_STATUSES: Final = frozenset({"queued", "ringing", "in_progress"})
NEVER_CONNECTED_STATUSES: Final = frozenset({"failed", "no_answer", "busy"})
# The worker may still post events in these (``ended`` accepts the final flush).
ACCEPTS_EVENTS_STATUSES: Final = frozenset({"queued", "ringing", "in_progress", "ended"})
WorkerStatus = Literal["ringing", "in_progress", "ended", "no_answer", "busy", "failed"]

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
DISCONNECT_REASONS: Final[tuple[DisconnectReason, ...]] = get_args(DisconnectReason)
RefusalReason = Literal["insufficient_credit", "concurrency_limit", "error"]
ControlReason = Literal["insufficient_credit", "error"]

Channel = Literal["web", "sip_inbound", "sip_outbound", "whatsapp"]
CHANNELS: Final[tuple[Channel, ...]] = get_args(Channel)
# Channels with a phone line on the other end: keypad tones, transfers and callbacks work here.
PHONE_CHANNELS: Final = frozenset({"sip_inbound", "sip_outbound"})
# Calls that arrive as a SIP participant and are routed by the API's inbound router at claim.
INBOUND_SIP_CHANNELS: Final = frozenset({"sip_inbound", "whatsapp"})
# Calls that reach real people outside the editor: always run the published version.
LIVE_CHANNELS: Final = frozenset({"sip_inbound", "sip_outbound", "whatsapp"})

# ``system`` transcript items the worker posts (call_events.yaml ``TranscriptItem.event``).
SystemEvent = Literal[
    "voicemail_detected",
    "silence_timeout",
    "max_duration",
    "credit_exhausted",
    "vendor_error",
    "segment_override",
    "override_clamped",
    "language_switched",
]
SYSTEM_EVENTS: Final[tuple[SystemEvent, ...]] = get_args(SystemEvent)

Direction = Literal["inbound", "outbound"]
Origin = Literal["live", "test", "simulation"]
ORIGINS: Final[tuple[Origin, ...]] = get_args(Origin)
AgentType = Literal["single_prompt", "flow"]

PipelineStep = Literal[
    "finalize_transcript", "price_and_charge", "analyze", "evaluate", "notify_analyzed", "complete"
]
PIPELINE_STEPS: Final[tuple[PipelineStep, ...]] = get_args(PipelineStep)
