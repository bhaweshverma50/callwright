"""Offline scripted-caller harness (Principle VII, research R20).

Runs a YAML script (``script_schema.py``) against an agent config with no network, keys or
telephony. The worker's own code does the work: ``plan_session`` and the adapter registry
(with fake vendors), the call-behaviour timers on a virtual clock, the pronunciation transform,
``RuntimeCallControl`` with segment overrides, the latency tracker, usage meters, the event
recorder and the event poster (against a fake internal API that checks the events contract).
What is simulated is the media: caller speech, vendor delays and audio playout.

Timing model per caller turn (livekit-agents 1.8, research R4): preemptive generation runs the
LLM and the TTS on the final transcript, so
``first_audio = max(eos + eou, eos + stt_final + llm_ttft + tts_ttfb)``; a tool call runs after
the turn commits (``max(eos + eou, eos + stt_final + llm_ttft) + tool + llm_ttft + tts_ttfb``).
With the semantic turn detector ``eou`` is ``max(stt_final, VAD_MIN_SILENCE_S,
min_endpointing_delay)``, or ``max_endpointing_delay`` for an utterance it sees as unfinished
(no closing punctuation, or a trailing digit string as in ``worker.turn_detection``); STT end of
turn uses ``max(stt_final, min_endpointing_delay)``.

A ``say`` written ``first part | second part`` is said with ``segment_pause_ms`` of silence
between the parts. Speech that resumes before the end-of-turn wait runs out continues the same
turn; a pause longer than the wait commits the turn early (a cut-off) and the rest is a new
caller turn that barges in on the reply.

CLI::

    python -m tests.harness.runner --config tests/harness/configs/default_agent.json \\
        --script tests/harness/scripts/greeting.yaml
"""

from __future__ import annotations

import argparse
import asyncio
import copy
import json
import sys
from collections.abc import Callable, Coroutine, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from callwright_contract.adapters import Kind
from callwright_contract.calls import ControlReason, DisconnectReason
from callwright_contract.protocol import FlushReason, RuntimeConfig
from callwright_contract.variables import BUILTIN_VARIABLES, builtin_values

from tests.harness.bench.synth import segments
from tests.harness.clock import VirtualClock, VirtualTimer
from tests.harness.fakes import FakeEventSink, FakeLLM, FakeSTT, FakeTTS, fake_registry
from tests.harness.script_schema import Script, Step, load_script
from worker.adapters.registry import AdapterRegistry, VendorSpec
from worker.agent import SessionPlan
from worker.audio import BackgroundAudioSpec, PronunciationTransform
from worker.call_behavior import (
    VAD_MIN_SILENCE_S,
    VOICEMAIL_TOOL_NAME,
    DtmfCollector,
    DurationTimer,
    InactivityTimer,
    VoicemailHandler,
)
from worker.control import RuntimeCallControl
from worker.entry import record_ending
from worker.internal_api import InternalApiClient
from worker.metrics import EventPoster, EventRecorder, LatencyTracker, TurnRecord, UsageMeters
from worker.pipeline import OverrideManager, SessionComponents, build_components, plan_session
from worker.tools import SegmentOverrides, ToolActivity
from worker.tools.dtmf import PressDigitExecutor
from worker.tools.registry import build_call_tools
from worker.turn_detection import ends_with_digit_string

HARNESS_DIR = Path(__file__).parent
DEFAULT_CONFIG = HARNESS_DIR / "configs" / "default_agent.json"
CLAIM_TABLES = HARNESS_DIR / "configs" / "claim_tables.json"
SCRIPTS_DIR = HARNESS_DIR / "scripts"
CALL_ID = "call_" + "01JA0HARNESS".ljust(26, "0")
EPOCH = datetime(2026, 10, 16, 12, 0, tzinfo=UTC)
WORDS_PER_SECOND = 2.6


def _raise_meter(meter: dict[tuple[str, str], int], key: tuple[str, str], ms: float) -> None:
    """Streamed audio so far: never lowered, so usage snapshots stay monotonic."""
    meter[key] = max(meter.get(key, 0), max(0, round(ms)))


def played_words(text: str, fraction: float) -> str:
    """An interrupted agent turn cut to the words actually played (FR-012)."""
    if fraction >= 1.0:
        return text
    words = text.split()
    return " ".join(words[: max(0, int(len(words) * max(0.0, fraction)))])


def deep_merge(base: Mapping[str, Any], over: Mapping[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(dict(base))
    for key, value in over.items():
        if isinstance(value, Mapping) and isinstance(out.get(key), Mapping):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def load_agent_config(path: str | Path = DEFAULT_CONFIG) -> dict[str, Any]:
    """An exported AgentVersion (``{"config": {...}}``) or a bare AgentConfig."""
    raw = json.loads(Path(path).read_text())
    config = raw.get("config", raw)
    if not isinstance(config, dict):
        raise ValueError(f"{path} has no AgentConfig")
    return config


def default_variables(config: Mapping[str, Any], channel: str) -> dict[str, str]:
    """What the API would resolve: agent defaults plus built-ins (FR-005)."""
    values = {
        str(v["name"]): str(v.get("default") or "")
        for v in config.get("dynamic_variables") or []
        if v.get("name")
    }
    known = builtin_values(
        call_id=CALL_ID,
        channel=channel,
        direction="inbound",
        from_number=None,
        to_number=None,
        timezone=None,
        now=EPOCH,
    )
    values.update({name: known[name] for name in BUILTIN_VARIABLES})
    return values


def claim_tables() -> dict[str, Any]:
    """The control ranges and STT Auto rules the API sends in every claim (written by the API's
    ``tests/unit/test_worker_claim_fixture.py``)."""
    tables: dict[str, Any] = json.loads(CLAIM_TABLES.read_text())
    return tables


def build_runtime(config: Mapping[str, Any], overrides: Mapping[str, Any]) -> RuntimeConfig:
    channel = str(overrides.get("channel", "web"))
    cb = config.get("call_behavior") or {}
    variables = default_variables(config, channel)
    variables.update({k: str(v) for k, v in (overrides.get("variables") or {}).items()})
    raw: dict[str, Any] = {
        "channel": channel,
        "direction": "outbound" if channel == "sip_outbound" else "inbound",
        "agent_id": "agt_harness",
        "agent_version_id": "agv_harness",
        "agent_type": config.get("type", "single_prompt"),
        "config": dict(config),
        "variables": variables,
        "limits": {
            "end_on_silence_s": cb["end_on_silence_s"],
            "max_duration_s": cb["max_duration_s"],
            "ring_duration_ms": cb["ring_duration_ms"],
        },
        **claim_tables(),
        "recording_enabled": True,
    }
    raw.update({k: v for k, v in overrides.items() if k not in ("variables", "channel")})
    return RuntimeConfig.model_validate(raw)


async def _no_sleep(seconds: float) -> None:
    return None


def tool_stubs(extra: Mapping[str, Any]) -> dict[str, Any]:
    """In-process stubs for 005 tools, from the script's ``runtime``: ``http_stub`` ({status,
    body, delay_ms}) answers HTTP tools and counts hits; ``kb_stub`` ({results, delay_ms})
    answers the internal knowledge search. Nothing touches the network."""
    import asyncio

    import httpx

    out: dict[str, Any] = {}

    async def public(host: str, port: int) -> list[str]:
        return ["93.184.216.34"]

    def handler(stub: Mapping[str, Any], body: Any) -> Any:
        async def respond(request: httpx.Request) -> httpx.Response:
            stub_hits.append(str(request.url))
            await asyncio.sleep(float(stub.get("delay_ms", 0)) / 1000)
            return httpx.Response(int(stub.get("status", 200)), json=body)

        return respond

    http_stub = extra.get("http_stub")
    if isinstance(http_stub, Mapping):
        transport = httpx.MockTransport(handler(http_stub, http_stub.get("body", {})))
        out["http_client"] = httpx.AsyncClient(transport=transport)
        out["resolver"] = public
    kb_stub = extra.get("kb_stub")
    if isinstance(kb_stub, Mapping):
        body = {
            "results": list(kb_stub.get("results") or []),
            "embedding_ms": 5,
            "query_ms": 3,
            "embedding_cache_hit": False,
        }
        transport = httpx.MockTransport(handler(kb_stub, body))
        out["api"] = InternalApiClient(
            "http://api.harness/v1/internal", "harness", http=httpx.AsyncClient(transport=transport)
        )
    return out


stub_hits: list[str] = []


# --------------------------------------------------------------------------------------------
# Result


@dataclass
class HarnessResult:
    name: str
    plan: SessionPlan
    end_reason: str | None
    duration_s: float
    history: list[dict[str, Any]]
    posted: list[dict[str, Any]]
    spoken: list[str]
    failures: list[str]
    violations: list[str]
    background: BackgroundAudioSpec | None
    usage: dict[str, Any]
    cutoffs: int = 0

    @property
    def ok(self) -> bool:
        return not self.failures and not self.violations

    @property
    def turns(self) -> list[dict[str, Any]]:
        return [e for e in self.posted if e["type"] == "turn"]

    @property
    def transcript(self) -> list[dict[str, Any]]:
        return [e["item"] for e in self.posted if e["type"] == "transcript_item"]

    def agent_messages(self) -> list[str]:
        return [
            i["text"] for i in self.transcript if i["type"] == "message" and i["role"] == "agent"
        ]

    def summary(self) -> dict[str, Any]:
        e2e = [t["e2e_ms"] for t in self.turns if t["turn_index"] > 0 and t["e2e_ms"] is not None]
        return {
            "script": self.name,
            "ok": self.ok,
            "end_reason": self.end_reason,
            "duration_s": round(self.duration_s, 3),
            "turns": len(self.turns),
            "e2e_ms": e2e,
            "greeting_ms": next((t["e2e_ms"] for t in self.turns if t["turn_index"] == 0), None),
            "events_posted": len(self.posted),
            "usage": self.usage,
            "failures": self.failures,
            "contract_violations": self.violations,
        }


# --------------------------------------------------------------------------------------------
# Scripted call


@dataclass
class Speech:
    turn: TurnRecord | None
    text: str
    spoken: str
    start: float
    end: float
    allow_interruptions: bool
    on_done: Callable[[], None] | None = None
    timer: VirtualTimer | None = None


@dataclass
class Generation:
    turn: TurnRecord | None
    timer: VirtualTimer
    first_audio_at: float


@dataclass
class HarnessCall:
    script: Script
    config: dict[str, Any]
    registry: AdapterRegistry | None = None
    clock: VirtualClock = field(default_factory=VirtualClock)

    def __post_init__(self) -> None:
        self.registry = fake_registry(self.script.fakes, self.registry)
        self.runtime = build_runtime(self.config, self.script.runtime)
        self.plan = plan_session(self.runtime, self.registry)
        self.components: SessionComponents = build_components(self.plan, self.registry, {})
        self.meters = UsageMeters()
        self.events: list[dict[str, Any]] = []
        self.recorder = EventRecorder(
            self.meters,
            wall_clock=self._wall,
            monotonic=self.clock.now,
            on_event=self.events.append,
        )
        self.tracker = LatencyTracker()
        self.sink = FakeEventSink(self.script.api.end_call_on_post, self.script.api.end_call_reason)
        self.poster = EventPoster(
            CALL_ID,
            self.recorder,
            self.sink,
            on_end_call=self._on_control_end,
            interval_s=float(self.runtime.heartbeat_interval_s),
            before_flush=self._update_time_meters,
        )
        self.overrides = OverrideManager(
            self.plan,
            self.registry,
            self.runtime.controls,
            self.runtime.stt_auto_rules,
            on_system_event=self.recorder.system,
        )
        self.control = RuntimeCallControl(CALL_ID, self.recorder, self, overrides=self.overrides)
        # 005: tools from the snapshot run through the real dispatch path (no telephony, no
        # network: HTTP tools need a canned response under ``runtime.simulation``).
        self.tools = build_call_tools(
            self.runtime,
            self.control,
            press_digit=PressDigitExecutor(sleep=_no_sleep),
            **tool_stubs(self.runtime.model_extra or {}),
        )
        self.transform = PronunciationTransform(self.plan.pronunciation)
        behavior = self.plan.behavior
        self.inactivity = InactivityTimer(
            self.clock, behavior.end_on_silence_s, lambda: self._hang_up_soon("inactivity")
        )
        self.duration = DurationTimer(
            self.clock, behavior.max_duration_s, lambda: self._hang_up_soon("max_duration_reached")
        )
        self.dtmf = (
            DtmfCollector(self.clock, behavior.dtmf, self._on_keypad_flush)
            if behavior.dtmf.enabled
            else None
        )
        self.voicemail = (
            VoicemailHandler(
                self.clock,
                behavior.voicemail,
                hang_up=lambda: self._hang_up_soon("voicemail_reached"),
                speak_message=self._leave_message,
            )
            if self.runtime.direction == "outbound" and behavior.voicemail.enabled
            else None
        )
        self.history: list[str] = []
        self.spoken: list[str] = []
        self.failures: list[str] = []
        self.cutoffs = 0
        self.ended = False
        self.end_reason: str | None = None
        self.ended_at: float | None = None
        self._pending: list[Coroutine[Any, Any, Any]] = []
        self._speech: Speech | None = None
        self._generation: Generation | None = None
        self._keypad: tuple[str, float] | None = None
        self._next_heartbeat = float(self.runtime.heartbeat_interval_s)
        self._stt_key = self._key("stt")
        self._stt_acc: dict[tuple[str, str], float] = {}
        self._stt_since = 0.0

    # basics ----------------------------------------------------------------

    def _wall(self) -> datetime:
        return EPOCH + timedelta(seconds=self.clock.now())

    def _key(self, kind: Kind) -> tuple[str, str]:
        spec: VendorSpec = self.components.get(kind).spec
        return spec.provider, spec.model or ""

    @property
    def stt(self) -> FakeSTT:
        stt: FakeSTT = self.components.stt
        return stt

    @property
    def llm(self) -> FakeLLM:
        llm: FakeLLM = self.components.llm
        return llm

    @property
    def tts(self) -> FakeTTS:
        tts: FakeTTS = self.components.tts
        return tts

    def _spawn(self, coro: Coroutine[Any, Any, Any]) -> None:
        self._pending.append(coro)

    def _hang_up_soon(self, reason: DisconnectReason, diagnostic: str | None = None) -> None:
        if not self.control.ending:
            self._spawn(self.control.hang_up(reason, diagnostic=diagnostic))

    def _on_control_end(self, reason: ControlReason) -> None:
        # Called inside the poster's flush: defer, the hang-up posts the final batch itself.
        self._hang_up_soon(reason)

    def _update_time_meters(self) -> None:
        now = self.clock.now() if self.ended_at is None else self.ended_at
        provider, model = self._stt_key
        total = self._stt_acc.get(self._stt_key, 0.0) + (now - self._stt_since) * 1000.0
        _raise_meter(self.meters.stt, (provider, model), total)
        for key, value in self._stt_acc.items():
            if key != self._stt_key:
                _raise_meter(self.meters.stt, key, value)
        nc = self.plan.nc
        self.meters.set_nc(nc.provider, nc.model or "", now * 1000.0)

    async def _drain(self) -> None:
        while self._pending:
            await self._pending.pop(0)

    async def advance_to(self, t: float) -> None:
        """Move virtual time to ``t``, firing timers and heartbeats in order."""
        while not self.ended:
            await self._drain()
            if self.ended:
                break
            target = min(t, self._next_heartbeat)
            if self.clock.fire_next(target):
                continue
            self.clock.set_time(target)
            if self._next_heartbeat <= t:
                await self.poster.flush()
                self._next_heartbeat += float(self.runtime.heartbeat_interval_s)
                continue
            break
        await self._drain()

    async def wait_idle(self, limit_s: float = 600.0) -> None:
        deadline = self.clock.now() + limit_s
        while (self._speech or self._generation) and not self.ended:
            due = self.clock.next_due()
            if due is None or due > deadline:
                break
            await self.advance_to(due)

    async def wait_first_audio(self) -> None:
        while self._generation is not None and not self.ended:
            await self.advance_to(self._generation.first_audio_at)

    # CallBackend -----------------------------------------------------------

    async def speak(self, text: str, allow_interruptions: bool) -> None:
        self._start_reply(None, text, self.tts.ttfb_s, allow_interruptions=allow_interruptions)

    async def send_dtmf(self, digits: str) -> None:
        return None

    async def caller_quiet(self) -> bool:
        return True

    async def end(self, reason: DisconnectReason, diagnostic: str | None) -> None:
        if self._speech is not None:
            self._speech_done(self._speech, interrupted=True, at=self.clock.now())
        if self._generation is not None:
            self._generation.timer.cancel()
            self._generation = None
        self.inactivity.stop()
        self.duration.stop()
        if self.dtmf is not None:
            self.dtmf.close()
        record_ending(self.recorder, reason, diagnostic)
        self.ended = True
        self.end_reason = reason
        self.ended_at = self.clock.now()
        await self.poster.flush()

    # agent speech ----------------------------------------------------------

    def _start_reply(
        self,
        turn: TurnRecord | None,
        text: str,
        latency_s: float,
        *,
        allow_interruptions: bool = True,
        on_done: Callable[[], None] | None = None,
    ) -> None:
        self.inactivity.busy_begin("agent")
        first = self.clock.now() + max(0.0, latency_s)

        def audio_start() -> None:
            self._generation = None
            self._audio_start(turn, text, allow_interruptions, on_done)

        self._generation = Generation(turn, self.clock.call_at(first, audio_start), first)

    def _audio_start(
        self,
        turn: TurnRecord | None,
        text: str,
        allow_interruptions: bool,
        on_done: Callable[[], None] | None,
    ) -> None:
        if self.ended:
            return
        now = self.clock.now()
        spoken = self.transform.apply(text)
        tts = self.tts
        self.meters.add_tts(tts.provider, tts.model, len(spoken))
        if turn is not None and self.tracker.current is turn:
            self.tracker.agent_audio_started(now)
        self.inactivity.activity()
        speech = Speech(
            turn, text, spoken, now, now + tts.duration_s(spoken), allow_interruptions, on_done
        )
        speech.timer = self.clock.call_at(speech.end, lambda: self._speech_done(speech, False))
        self._speech = speech
        self.spoken.append(spoken)

    def _speech_done(self, speech: Speech, interrupted: bool, at: float | None = None) -> None:
        if self._speech is not speech:
            return
        self._speech = None
        if speech.timer is not None:
            speech.timer.cancel()
        played = speech.text
        if interrupted:
            span = max(1e-9, speech.end - speech.start)
            played = played_words(speech.text, ((at or speech.end) - speech.start) / span)
        start_ms = self.recorder.offset_ms(speech.start)
        end_ms = self.recorder.offset_ms(at if interrupted and at is not None else speech.end)
        if speech.turn is not None:
            speech.turn.interrupted = interrupted
            speech.turn.text = speech.text
            speech.turn.played_text = played
            self.recorder.turn(speech.turn)
        self.recorder.message(
            "agent",
            played,
            started_ms=start_ms,
            ended_ms=end_ms,
            turn_index=speech.turn.turn_index if speech.turn else None,
            interrupted=interrupted,
        )
        self.history.append(played)
        self.inactivity.busy_end("agent")
        self._turn_boundary()
        if speech.on_done is not None and not interrupted:
            speech.on_done()

    def _turn_boundary(self) -> None:
        swap = self.overrides.apply_pending()
        if swap is None:
            return
        assert self.registry is not None
        for kind in swap.kinds:
            if kind == "stt":
                now = self.clock.now()
                self._stt_acc[self._stt_key] = (
                    self._stt_acc.get(self._stt_key, 0.0) + (now - self._stt_since) * 1000.0
                )
                self._stt_since = now
            self.components.set(kind, self.registry.build(swap.specs[kind], {}))
            if kind == "stt":
                self._stt_key = self._key("stt")

    def _leave_message(self, message: str) -> None:
        self._start_reply(
            None,
            message,
            self.tts.ttfb_s,
            allow_interruptions=False,
            on_done=lambda: self._hang_up_soon("voicemail_reached"),
        )

    # opening ---------------------------------------------------------------

    async def connect(self) -> None:
        self.recorder.connected()
        self.tracker.connected(self.clock.now())
        self.recorder.status("in_progress")
        for note in self.plan.behavior.notes:
            self.recorder.warning(
                "config_value_clamped",
                component="runtime",
                detail=f"{note.path} {note.value} -> {note.clamped_to}",
            )
        for warning in self.plan.warnings:
            self.recorder.warning(warning.code, component="runtime", detail=warning.detail)
        self.inactivity.start()
        self.duration.start()
        if self.voicemail is not None:
            self.voicemail.answered()
        if self.plan.start_speaker != "agent":
            return
        turn = self.tracker.begin_turn(greeting=True)
        tts = self.tts
        if self.plan.greeting:
            text, latency = self.plan.greeting, tts.ttfb_s
        else:
            reply = self.llm.respond(self.plan.instructions, [], None)
            self._meter_llm(reply.input_tokens, reply.cached_input_tokens, reply.output_tokens)
            self.tracker.component("llm_ttft", self.llm.ttft_s)
            text, latency = reply.text, self.llm.ttft_s + tts.ttfb_s
        self.tracker.component("tts_ttfb", tts.ttfb_s)
        self._start_reply(turn, text, latency)

    def _meter_llm(self, input_tokens: int, cached: int, output: int) -> None:
        llm = self.llm
        self.meters.add_llm(
            llm.provider,
            llm.model,
            input_tokens=input_tokens,
            cached_input_tokens=cached,
            output_tokens=output,
        )

    # caller ----------------------------------------------------------------

    async def caller_says(self, step: Step, text: str, *, machine: bool = False) -> None:
        if step.interrupt_after_ms is None:
            await self.wait_idle()
            if self.ended:
                return
            await self.advance_to(self.clock.now() + step.pause_ms / 1000.0)
        else:
            await self.wait_first_audio()
            base = self._speech.start if self._speech is not None else self.clock.now()
            await self.advance_to(max(self.clock.now(), base + step.interrupt_after_ms / 1000.0))
        if self.ended:
            return
        parts = segments(text) or [text]
        await self._utterance(step, parts, machine=machine)

    async def _utterance(self, step: Step, parts: list[str], *, machine: bool) -> None:
        """One caller turn said as ``parts`` with ``segment_pause_ms`` between them."""
        pause_s = step.segment_pause_ms / 1000.0
        start = self.clock.now()
        self.inactivity.activity()
        self.inactivity.busy_begin("caller")
        if self.voicemail is not None:
            self.voicemail.caller_speech_started()
        heard: list[str] = []
        for i, part in enumerate(parts):
            duration = (
                step.duration_ms / 1000.0
                if step.duration_ms is not None and len(parts) == 1
                else max(0.4, len(part.split()) / WORDS_PER_SECOND)
            )
            part_start = self.clock.now()
            self._maybe_interrupt(part, part_start, duration)
            await self.advance_to(part_start + duration)
            if self.ended:
                return
            heard.append(part)
            last = i == len(parts) - 1
            if not last and pause_s < self.end_of_turn_s(" ".join(heard)):
                # The caller resumes inside the end-of-turn wait: same turn (R4).
                await self.advance_to(self.clock.now() + pause_s)
                if self.ended:
                    return
                continue
            eos = self.clock.now()
            self.inactivity.busy_end("caller")
            if self.voicemail is not None:
                self.voicemail.caller_speech_ended()
            self.tracker.user_speech_ended(eos)
            if self._speech is not None or self._generation is not None:
                return  # spoke over an uninterruptible agent: input discarded
            await self._respond(" ".join(heard), eos, start, machine=machine)
            if last or self.ended:
                return
            # Cut off: the pause outlasted the wait, so the rest is a new caller turn.
            self.cutoffs += 1
            await self.advance_to(eos + pause_s)
            if self.ended:
                return
            await self._utterance(step, parts[i + 1 :], machine=machine)
            return

    def _maybe_interrupt(self, text: str, start: float, duration: float) -> None:
        params = self.plan.behavior.interruption
        if not params.allow_interruptions:
            return
        long_enough = duration >= params.min_interruption_duration
        enough_words = len(text.split()) >= params.min_interruption_words
        if not (long_enough and enough_words):
            return
        at = start + params.min_interruption_duration
        speech = self._speech
        if speech is not None and speech.allow_interruptions and at < speech.end:
            self.clock.call_at(at, lambda: self._speech_done(speech, True, at=at))
        generation = self._generation
        if generation is not None and speech is None:
            generation.timer.cancel()
            self._generation = None
            self.inactivity.busy_end("agent")

    def end_of_turn_s(self, text: str) -> float:
        """Seconds from the end of caller speech to the turn committing (R4, R5)."""
        endpointing = self.plan.behavior.endpointing
        stt_s = self.stt.final_delay_s
        if self.plan.turn_detection == "stt":
            return max(stt_s, endpointing.min_endpointing_delay)
        finished = text.rstrip().endswith((".", "?", "!")) and not ends_with_digit_string(text)
        delay = endpointing.min_endpointing_delay if finished else endpointing.max_endpointing_delay
        return max(stt_s, VAD_MIN_SILENCE_S, delay)

    async def _respond(
        self, text: str, eos: float, started: float, *, machine: bool = False, keypad: bool = False
    ) -> None:
        behavior = self.plan.behavior
        stt_s = 0.0 if keypad else self.stt.final_delay_s
        eou_s = 0.0 if keypad else self.end_of_turn_s(text)
        await self.advance_to(eos + stt_s)
        if self.ended:
            return
        self.recorder.message(
            "user",
            text,
            started_ms=self.recorder.offset_ms(started),
            ended_ms=self.recorder.offset_ms(eos),
            confidence=None if keypad else 0.95,
            source="keypad" if keypad else "voice",
        )
        self.history.append(text)
        self._turn_boundary()
        llm = self.llm
        preemptive = self.script.fakes.preemptive_generation and not keypad
        text_ready = max(eos + eou_s, eos + (stt_s if preemptive else eou_s) + llm.ttft_s)

        if machine and self.voicemail is not None and self.voicemail.active():
            await self.advance_to(text_ready)
            if self.ended:
                return
            reply = llm.respond(self.plan.instructions, self.history, text)
            self._meter_llm(reply.input_tokens, reply.cached_input_tokens, 0)
            self.control.report_tool(ToolActivity(VOICEMAIL_TOOL_NAME, arguments={}))
            self.voicemail.report_machine()
            await self._drain()
            return

        turn = self.tracker.begin_turn()
        self.tracker.component("stt_final", stt_s if not keypad else None)
        self.tracker.component("eou_delay", eou_s)
        reply = llm.respond(self.plan.instructions, self.history, text)
        self._meter_llm(reply.input_tokens, reply.cached_input_tokens, reply.output_tokens)
        self.tracker.component("llm_ttft", llm.ttft_s)
        extra_s = 0.0
        rule = reply.rule
        if rule is not None and rule.tool:
            extra_s = rule.tool_ms / 1000.0 + llm.ttft_s  # tool run, then the follow-up generation
            self.tracker.component("tool", rule.tool_ms / 1000.0)
            if rule.tool in self.tools.by_name:
                await self.tools.dispatch(rule.tool, rule.tool_arguments)
            else:
                self.control.report_tool(
                    ToolActivity(
                        rule.tool,
                        arguments=rule.tool_arguments,
                        output=rule.tool_output,
                        duration_ms=round(rule.tool_ms),
                    )
                )
        if rule is not None and rule.transition:
            self.control.report_transition(rule.transition, label=rule.match or None)
        tts = self.tts
        self.tracker.component("tts_ttfb", tts.ttfb_s)
        first_audio = text_ready + extra_s + tts.ttfb_s
        if preemptive and behavior.endpointing.preemptive_tts and not extra_s:
            # Preemptive TTS: the reply audio is synthesized during the end-of-turn wait.
            first_audio = max(eos + eou_s, eos + stt_s + llm.ttft_s + tts.ttfb_s)
        on_done = (
            (lambda: self._hang_up_soon("agent_hangup"))
            if rule is not None and rule.end_call
            else None
        )
        self._start_reply(turn, reply.text, first_audio - self.clock.now(), on_done=on_done)

    async def keypad(self, step: Step, digits: str) -> None:
        await self.wait_idle()
        for digit in digits:
            if self.ended:
                return
            await self.advance_to(self.clock.now() + step.digit_interval_ms / 1000.0)
            self.inactivity.activity()
            if self.dtmf is not None:
                self.dtmf.add(digit)
        if self.dtmf is not None and self._keypad is None:
            await self.advance_to(self.clock.now() + self.plan.behavior.dtmf.timeout_ms / 1000.0)
        if self._keypad is not None and not self.ended:
            flushed, at = self._keypad
            self._keypad = None
            self.tracker.user_speech_ended(at)
            await self._respond(flushed, at, at, keypad=True)

    def _on_keypad_flush(self, digits: str, reason: FlushReason) -> None:
        self.recorder.dtmf(digits, "received", reason)
        self._keypad = (digits, self.clock.now())

    # expectations ----------------------------------------------------------

    def _fail(self, step: Step, message: str) -> None:
        self.failures.append(f"{self.script.name}: {message}")

    def _last(self, role: str) -> dict[str, Any] | None:
        for event in reversed(self.events):
            item = event.get("item")
            if (
                isinstance(item, dict)
                and item.get("type") == "message"
                and item.get("role") == role
            ):
                return dict(item)
        return None

    @staticmethod
    def _matches(event: Mapping[str, Any], want: Mapping[str, Any]) -> bool:
        flat: dict[str, Any] = {}
        item = event.get("item")
        if isinstance(item, Mapping):
            flat.update(item)
            flat["item_type"] = item.get("type")
        flat.update({k: v for k, v in event.items() if k != "item"})
        return all(str(flat.get(k)) == str(v) for k, v in want.items())

    async def check(self, step: Step) -> None:
        expects = {
            k for k, v in step.model_dump().items() if k.startswith("expect_") and v is not None
        }
        if expects and not self.ended:
            await self.wait_idle()  # assertions see the agent's finished reply
        history = self.events
        if step.expect_agent_says is not None:
            last = self._last("agent")
            if last is None or step.expect_agent_says.lower() not in last["text"].lower():
                self._fail(
                    step, f"agent said {last and last['text']!r}, wanted {step.expect_agent_says!r}"
                )
        if step.expect_agent_speaks is not None:
            spoken = self.spoken[-1] if self.spoken else ""
            if step.expect_agent_speaks.lower() not in spoken.lower():
                self._fail(step, f"agent spoke {spoken!r}, wanted {step.expect_agent_speaks!r}")
        if step.expect_user_says is not None:
            last = self._last("user")
            if last is None or step.expect_user_says != last["text"]:
                self._fail(
                    step, f"user turn {last and last['text']!r}, wanted {step.expect_user_says!r}"
                )
        if step.expect_tool is not None and not any(
            e["type"] == "tool_call" and e["name"] == step.expect_tool for e in history
        ):
            self._fail(step, f"no tool call {step.expect_tool}")
        if step.expect_transition is not None and not any(
            e["type"] == "flow_transition" and e["to_node_id"] == step.expect_transition
            for e in history
        ):
            self._fail(step, f"no transition to {step.expect_transition}")
        if step.expect_end_reason is not None and (self.end_reason or "none") != (
            step.expect_end_reason
        ):
            self._fail(step, f"end reason {self.end_reason}, wanted {step.expect_end_reason}")
        turns = [e for e in history if e["type"] == "turn"]
        if step.expect_within_ms is not None:
            last_turn = turns[-1] if turns else None
            e2e = last_turn["e2e_ms"] if last_turn else None
            if e2e is None or e2e > step.expect_within_ms:
                self._fail(step, f"last turn e2e {e2e} ms, budget {step.expect_within_ms} ms")
        if step.expect_interrupted is not None:
            last_turn = turns[-1] if turns else None
            if last_turn is None or last_turn["interrupted"] != step.expect_interrupted:
                self._fail(step, f"last turn interrupted={last_turn and last_turn['interrupted']}")
        if step.expect_turns is not None and len(turns) != step.expect_turns:
            self._fail(step, f"{len(turns)} turns, wanted {step.expect_turns}")
        if step.expect_cutoffs is not None and self.cutoffs != step.expect_cutoffs:
            self._fail(step, f"{self.cutoffs} cut-offs, wanted {step.expect_cutoffs}")
        if step.expect_event is not None and not any(
            self._matches(e, step.expect_event) for e in history
        ):
            self._fail(step, f"no event matching {step.expect_event}")
        if step.expect_no_event is not None and any(
            self._matches(e, step.expect_no_event) for e in history
        ):
            self._fail(step, f"unexpected event matching {step.expect_no_event}")
        if step.expect_meter is not None:
            self._update_time_meters()
            want = dict(step.expect_meter)
            kind = want.pop("kind")
            minimum = want.pop("min", 1)
            rows = self.meters.snapshot()[kind]
            value_key = {"stt": "audio_ms", "tts": "characters", "nc": "audio_ms"}.get(
                kind, "output_tokens"
            )
            if not any(
                all(str(r.get(k)) == str(v) for k, v in want.items())
                and r.get(value_key, 0) >= minimum
                for r in rows
            ):
                self._fail(step, f"no {kind} meter {want} >= {minimum}: {rows}")
        if step.expect_background is not None:
            bg = self.plan.background
            got = {"kind": bg.kind, "ref": bg.ref, "gain": bg.gain} if bg else None
            if got is None or any(
                str(got.get(k)) != str(v) for k, v in step.expect_background.items()
            ):
                self._fail(step, f"background {got}, wanted {step.expect_background}")

    # run -------------------------------------------------------------------

    async def run(self) -> HarnessResult:
        await self.connect()
        for step in self.script.steps:
            if not self.ended:
                await self._act(step)
            await self.check(step)
        if not self.ended:
            await self.wait_idle()
            await self.control.hang_up("user_hangup")
        await self._drain()
        snapshot: dict[str, Any] = next(
            (e["usage"] for e in reversed(self.sink.events) if e["type"] == "usage"), {}
        )
        return HarnessResult(
            name=self.script.name,
            plan=self.plan,
            end_reason=self.end_reason,
            duration_s=self.ended_at if self.ended_at is not None else self.clock.now(),
            history=list(self.events),
            posted=self.sink.events,
            spoken=list(self.spoken),
            failures=list(self.failures),
            violations=list(self.sink.violations),
            background=self.plan.background,
            usage=snapshot,
            cutoffs=self.cutoffs,
        )

    async def _act(self, step: Step) -> None:
        if step.say is not None:
            await self.caller_says(step, step.say)
        elif step.machine_greeting is not None:
            await self.caller_says(step, step.machine_greeting, machine=True)
        elif step.silence_s is not None:
            await self.advance_to(self.clock.now() + step.silence_s)
        elif step.dtmf is not None:
            await self.keypad(step, step.dtmf)
        elif step.override is not None:
            overrides: SegmentOverrides = step.override  # type: ignore[assignment]
            await self.control.apply_overrides(overrides)
        elif step.hangup:
            await self.wait_idle()
            await self.control.hang_up("user_hangup")
        elif step.wait_idle:
            await self.wait_idle()


async def run_script(
    script: Script | str | Path,
    config: Mapping[str, Any] | None = None,
    *,
    config_overrides: Mapping[str, Any] | None = None,
) -> HarnessResult:
    """Run one script. ``config`` defaults to the script's ``config_file`` or the default agent."""
    if not isinstance(script, Script):
        script = load_script(script)
    if config is None:
        source = (SCRIPTS_DIR / script.config_file) if script.config_file else DEFAULT_CONFIG
        config = load_agent_config(source)
    merged = deep_merge(config, script.config)
    if config_overrides:
        merged = deep_merge(merged, config_overrides)
    call = HarnessCall(script, merged)
    return await call.run()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a scripted caller offline.")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG), help="AgentVersion JSON")
    parser.add_argument("--script", required=True, help="YAML script")
    args = parser.parse_args(argv)
    result = asyncio.run(run_script(args.script, load_agent_config(args.config)))
    print(json.dumps(result.summary(), indent=2))
    return 0 if result.ok else 1


if __name__ == "__main__":
    sys.exit(main())
