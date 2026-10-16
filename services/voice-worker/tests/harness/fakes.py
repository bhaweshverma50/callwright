"""Fake vendors and a fake internal API for the offline harness (research R20).

The fakes are built through the real :class:`worker.adapters.registry.AdapterRegistry` (its
builders are swapped), so the catalog checks, Auto STT resolution and spec options are the same
as on a live call. No network, no keys.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from tests.harness.script_schema import Fakes, LlmRule
from worker.adapters.registry import AdapterRegistry, VendorSpec
from worker.internal_api import CallClosed, Control, EventBatchResult

# --------------------------------------------------------------------------------------------
# Fake vendors


def _timing(fakes: Fakes, spec: VendorSpec, field_name: str, default: float) -> float:
    for key in (f"{spec.kind}/{spec.provider}/{spec.model}", f"{spec.kind}/{spec.provider}"):
        vt = fakes.vendors.get(key)
        if vt is not None and getattr(vt, field_name) is not None:
            return float(getattr(vt, field_name))
    return default


@dataclass
class FakeSTT:
    spec: VendorSpec
    final_delay_s: float

    @property
    def provider(self) -> str:
        return self.spec.provider

    @property
    def model(self) -> str:
        return self.spec.model or ""


@dataclass
class FakeReply:
    text: str
    rule: LlmRule | None = None
    input_tokens: int = 0
    cached_input_tokens: int = 0
    output_tokens: int = 0


@dataclass
class FakeLLM:
    spec: VendorSpec
    ttft_s: float
    rules: Sequence[LlmRule]
    default_reply: str
    greeting_reply: str
    _previous_input: int = 0

    @property
    def provider(self) -> str:
        return self.spec.provider

    @property
    def model(self) -> str:
        return self.spec.model or ""

    def respond(
        self, instructions: str, history: Sequence[str], user_text: str | None
    ) -> FakeReply:
        """Rule-based reply. ``user_text=None`` is the generated opening line."""
        if user_text is None:
            text, rule = self.greeting_reply, None
        else:
            rule = next((r for r in self.rules if r.match.lower() in user_text.lower()), None)
            text = rule.reply if rule is not None else self.default_reply
        prompt_chars = len(instructions) + sum(len(h) for h in history) + len(user_text or "")
        input_tokens = max(1, prompt_chars // 4)
        cached = min(self._previous_input, input_tokens)
        self._previous_input = input_tokens
        return FakeReply(
            text=text,
            rule=rule,
            input_tokens=input_tokens,
            cached_input_tokens=cached,
            output_tokens=max(1, len(text) // 4) if text else 0,
        )


@dataclass
class FakeTTS:
    spec: VendorSpec
    ttfb_s: float
    ms_per_char: float

    @property
    def provider(self) -> str:
        return self.spec.provider

    @property
    def model(self) -> str | None:
        return self.spec.model

    def duration_s(self, text: str) -> float:
        speed = float(self.spec.options.get("speed", 1.0)) or 1.0
        return len(text) * self.ms_per_char / 1000.0 / speed


@dataclass
class FakeNC:
    spec: VendorSpec


def fake_registry(fakes: Fakes, base: AdapterRegistry | None = None) -> AdapterRegistry:
    """The real registry (catalog, checks) with every builder replaced by a fake."""

    def build(spec: VendorSpec, creds: Mapping[str, str]) -> Any:
        if spec.kind == "stt":
            return FakeSTT(spec, _timing(fakes, spec, "stt_final_ms", fakes.stt_final_ms) / 1000)
        if spec.kind == "llm":
            return FakeLLM(
                spec,
                _timing(fakes, spec, "llm_ttft_ms", fakes.llm_ttft_ms) / 1000,
                fakes.rules,
                fakes.default_reply,
                fakes.greeting_reply,
            )
        if spec.kind == "tts":
            return FakeTTS(
                spec,
                _timing(fakes, spec, "tts_ttfb_ms", fakes.tts_ttfb_ms) / 1000,
                _timing(fakes, spec, "ms_per_char", fakes.ms_per_char),
            )
        return FakeNC(spec)

    return (base or AdapterRegistry()).with_builders(default_builder=build)


# --------------------------------------------------------------------------------------------
# Fake internal API (events endpoint) with contract checks

EVENT_TYPES = {
    "status",
    "turn",
    "transcript_item",
    "usage",
    "tool_call",
    "flow_transition",
    "dtmf",
    "warning",
    "error",
}
REQUIRED = {
    "status": ("status",),
    "turn": ("turn_index",),
    "transcript_item": ("item",),
    "usage": ("usage",),
    "tool_call": ("name",),
    "flow_transition": ("to_node_id",),
    "dtmf": ("digits", "direction"),
    "warning": ("code",),
    "error": ("code",),
}
STATUSES = {"ringing", "in_progress", "ended", "no_answer", "busy", "failed"}
REASONS = {
    "user_hangup",
    "agent_hangup",
    "call_transfer",
    "voicemail_reached",
    "inactivity",
    "max_duration_reached",
    "error",
    "concurrency_limit",
    "insufficient_credit",
}
SYSTEM_EVENTS = {
    "voicemail_detected",
    "silence_timeout",
    "max_duration",
    "credit_exhausted",
    "vendor_error",
    "segment_override",
    "override_clamped",
}
DIGITS = re.compile(r"^[0-9*#]{1,99}$")


def contract_errors(event: Mapping[str, Any]) -> list[str]:
    """Check one event against ``contracts/call_events.yaml`` (the parts the worker controls)."""
    errors: list[str] = []
    for key in ("seq", "type", "occurred_at"):
        if key not in event:
            errors.append(f"missing {key}")
    kind = event.get("type")
    if kind not in EVENT_TYPES:
        return [*errors, f"unknown type {kind}"]
    if not isinstance(event.get("seq"), int) or event["seq"] < 1:
        errors.append("seq must be an integer >= 1")
    errors += [f"{kind} missing {k}" for k in REQUIRED[str(kind)] if k not in event]
    if kind == "status":
        if event.get("status") not in STATUSES:
            errors.append(f"bad status {event.get('status')}")
        reason = event.get("disconnect_reason")
        if reason is not None and reason not in REASONS:
            errors.append(f"bad disconnect_reason {reason}")
    if kind == "dtmf" and not DIGITS.match(str(event.get("digits", ""))):
        errors.append("bad digits")
    if kind == "transcript_item":
        item = event.get("item") or {}
        if item.get("type") == "system" and item.get("event") not in SYSTEM_EVENTS:
            errors.append(f"bad system event {item.get('event')}")
        if len(str(item.get("output", ""))) > 8192:
            errors.append("tool output too long")
    if kind == "usage":
        usage = event.get("usage") or {}
        for comp, need in (
            ("stt", ("provider", "model", "audio_ms")),
            ("llm", ("provider", "model", "input_tokens", "output_tokens")),
            ("tts", ("provider", "characters")),
            ("nc", ("provider", "audio_ms")),
        ):
            for row in usage.get(comp, []):
                errors += [f"usage.{comp} missing {k}" for k in need if k not in row]
                errors += [
                    f"usage.{comp}.{k} negative"
                    for k, v in row.items()
                    if isinstance(v, int) and v < 0
                ]
    return errors


@dataclass
class FakeEventSink:
    """Records posted batches; can order ``end_call`` and enforces seq and contract rules."""

    end_call_on_post: int | None = None
    end_call_reason: Literal["insufficient_credit", "error"] = "insufficient_credit"
    batches: list[list[dict[str, Any]]] = field(default_factory=list)
    violations: list[str] = field(default_factory=list)
    closed: bool = False
    _last_seq: int = 0

    async def post_events(self, call_id: str, events: Sequence[dict[str, Any]]) -> EventBatchResult:
        if self.closed:
            raise CallClosed(409, "call is terminal")
        self.batches.append([dict(e) for e in events])
        for event in events:
            for error in contract_errors(event):
                self.violations.append(f"seq {event.get('seq')}: {error}")
            if event.get("seq", 0) <= self._last_seq:
                self.violations.append(f"seq {event.get('seq')} not increasing")
            self._last_seq = max(self._last_seq, int(event.get("seq", 0)))
        if any(e.get("type") == "status" and e.get("status") == "ended" for e in events):
            self.closed = True
        control = Control()
        if self.end_call_on_post is not None and len(self.batches) == self.end_call_on_post:
            control = Control(action="end_call", disconnect_reason=self.end_call_reason)
        return EventBatchResult(accepted=len(events), duplicates=0, control=control)

    @property
    def events(self) -> list[dict[str, Any]]:
        return [e for batch in self.batches for e in batch]


# --------------------------------------------------------------------------------------------
# livekit-agents compatible LLM for text-mode sessions (real AgentSession, no network)


def scripted_llm(reply: str) -> Any:
    """An ``llm.LLM`` that streams one fixed reply and reports token usage."""
    from livekit.agents import llm
    from livekit.agents.types import DEFAULT_API_CONNECT_OPTIONS, APIConnectOptions

    class ScriptedStream(llm.LLMStream):
        async def _run(self) -> None:
            self._event_ch.send_nowait(
                llm.ChatChunk(id="fake", delta=llm.ChoiceDelta(role="assistant", content=reply))
            )
            self._event_ch.send_nowait(
                llm.ChatChunk(
                    id="fake",
                    usage=llm.CompletionUsage(
                        completion_tokens=max(1, len(reply) // 4),
                        prompt_tokens=100,
                        prompt_cached_tokens=40,
                        total_tokens=100 + max(1, len(reply) // 4),
                    ),
                )
            )

    class ScriptedLLM(llm.LLM):  # type: ignore[type-arg]
        def __init__(self) -> None:
            super().__init__()
            self.requests: list[Any] = []

        @property
        def model(self) -> str:
            return "gpt-5.1"

        @property
        def provider(self) -> str:
            return "fake"

        def chat(
            self,
            *,
            chat_ctx: Any,
            tools: list[Any] | None = None,
            conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS,
            **_: Any,
        ) -> Any:
            self.requests.append(chat_ctx)
            return ScriptedStream(
                self, chat_ctx=chat_ctx, tools=tools or [], conn_options=conn_options
            )

    return ScriptedLLM()
