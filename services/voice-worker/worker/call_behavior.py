"""Call behaviour: turn-taking mapping, silence and duration timers, keypad input, voicemail.

Everything here runs on a :class:`Clock` so the offline harness drives it with a virtual clock
(research R9, R20). Live calls use :class:`AsyncioClock`.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

# --------------------------------------------------------------------------------------------
# Clock


class TimerHandle(Protocol):
    def cancel(self) -> None: ...


class Clock(Protocol):
    def now(self) -> float:
        """Monotonic seconds."""
        ...

    def call_later(self, delay_s: float, callback: Callable[[], None]) -> TimerHandle: ...


class AsyncioClock:
    """Clock backed by the running event loop."""

    def __init__(self, loop: asyncio.AbstractEventLoop | None = None) -> None:
        self._loop = loop

    @property
    def loop(self) -> asyncio.AbstractEventLoop:
        return self._loop or asyncio.get_running_loop()

    def now(self) -> float:
        return self.loop.time()

    def call_later(self, delay_s: float, callback: Callable[[], None]) -> TimerHandle:
        return self.loop.call_later(max(0.0, delay_s), callback)


# --------------------------------------------------------------------------------------------
# Turn-taking mapping (research R4). The table below is the only place to change calibration.
#
# How livekit-agents 1.8 ends a caller turn with the semantic turn detector: Silero VAD reports
# end of speech after ``VAD_MIN_SILENCE_S`` of silence, the turn-detector model scores the
# transcript, and the turn commits ``min_delay`` after the last speech when the model thinks the
# caller is done, or ``max_delay`` after it when the model thinks they are not. Speech that
# resumes inside the wait cancels it. So the shortest possible wait is
# ``max(VAD_MIN_SILENCE_S, min_delay)`` and ``max_delay`` is the longest mid-sentence pause the
# agent sits through. Preemptive generation runs the LLM and TTS during the wait.

VAD_MIN_SILENCE_S = 0.3
"""Silero ``min_silence_duration`` (framework default 0.55 s). It is the floor of every end of
turn, so it must not exceed the fastest ``min_endpointing_delay``; it stays above the 0.25 s
minimum the audio turn detector requires."""

FALSE_INTERRUPTION_TIMEOUT_S = 1.0
"""Silence after a barge-in with no transcript before the agent resumes (framework default
2.0 s). Streaming STT finals land within about 0.5 s of the end of speech, so 1.0 s still
tells a short word from a cough while the agent stops for half as long after noise."""


@dataclass(frozen=True)
class InterruptionParams:
    allow_interruptions: bool
    min_interruption_duration: float
    min_interruption_words: int
    resume_false_interruption: bool = True
    false_interruption_timeout: float = FALSE_INTERRUPTION_TIMEOUT_S


@dataclass(frozen=True)
class EndpointingParams:
    min_endpointing_delay: float
    max_endpointing_delay: float
    preemptive_tts: bool = True


def _unit(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def map_interruption(sensitivity: float) -> InterruptionParams:
    """Interruption sensitivity s in 0..1; 0 disables interruptions, higher interrupts sooner.

    ``min_interruption_duration = 0.2 + (1 - s) * 0.6`` seconds;
    ``min_interruption_words = 0 if s >= 0.7 else (1 if s >= 0.3 else 2)``. A barge-in with no
    transcript after ``FALSE_INTERRUPTION_TIMEOUT_S`` of silence is false and the agent resumes.
    """
    s = _unit(sensitivity)
    words = 0 if s >= 0.7 else (1 if s >= 0.3 else 2)
    return InterruptionParams(
        allow_interruptions=s > 0.0,
        min_interruption_duration=round(0.2 + (1.0 - s) * 0.6, 4),
        min_interruption_words=words,
    )


def map_responsiveness(responsiveness: float) -> EndpointingParams:
    """Responsiveness r in 0..1; higher replies sooner.

    ``min_endpointing_delay = 0.3 + (1 - r) * 0.5`` seconds: the wait after a turn the model
    reads as finished, never below ``VAD_MIN_SILENCE_S`` (a lower value would have no effect).
    ``max_endpointing_delay = 0.9 + (1 - r) * 1.6`` seconds: the longest mid-sentence pause the
    agent waits through when the model reads the turn as unfinished (1.22 s at the default
    0.8, 2.5 s at 0, the framework's ceiling).
    """
    r = _unit(responsiveness)
    return EndpointingParams(
        min_endpointing_delay=round(VAD_MIN_SILENCE_S + (1.0 - r) * 0.5, 4),
        max_endpointing_delay=round(0.9 + (1.0 - r) * 1.6, 4),
    )


# --------------------------------------------------------------------------------------------
# Limits read from the version, clamped as defence in depth (003 data-model section 10)

LIMIT_RANGES: Mapping[str, tuple[float, float]] = {
    "end_on_silence_s": (10, 300),
    "max_duration_s": (30, 3600),
    "ring_duration_ms": (0, 30000),
    "dtmf.timeout_ms": (1000, 10000),
    "dtmf.digits": (1, 99),
    "interruption_sensitivity": (0, 1),
    "responsiveness": (0, 1),
    "background_audio.volume": (0, 3),
}


@dataclass
class ClampNote:
    path: str
    value: Any
    clamped_to: Any


def clamp_limit(path: str, value: float, notes: list[ClampNote]) -> float:
    low, high = LIMIT_RANGES[path]
    clamped = max(low, min(high, value))
    if clamped != value:
        notes.append(ClampNote(path, value, clamped))
    return clamped


@dataclass(frozen=True)
class DtmfConfig:
    enabled: bool = False
    timeout_ms: int = 2500
    termination_key: str | None = "#"
    digits: int = 10


@dataclass(frozen=True)
class VoicemailConfig:
    enabled: bool = False
    action: Literal["hang_up", "leave_message"] = "hang_up"
    message: str | None = None


@dataclass(frozen=True)
class CallBehavior:
    end_on_silence_s: float
    max_duration_s: float
    ring_duration_ms: int
    interruption: InterruptionParams
    endpointing: EndpointingParams
    dtmf: DtmfConfig
    voicemail: VoicemailConfig
    notes: tuple[ClampNote, ...] = field(default_factory=tuple)


def behavior_from_config(
    config: Mapping[str, Any], limits: Mapping[str, Any] | None = None
) -> CallBehavior:
    """Build call behaviour from an AgentConfig and the claim's ``limits`` (limits win)."""
    notes: list[ClampNote] = []
    cb: Mapping[str, Any] = config.get("call_behavior") or {}
    adv: Mapping[str, Any] = config.get("advanced") or {}
    lim: Mapping[str, Any] = limits or {}

    silence = clamp_limit(
        "end_on_silence_s",
        float(lim.get("end_on_silence_s", cb.get("end_on_silence_s", 30))),
        notes,
    )
    max_duration = clamp_limit(
        "max_duration_s", float(lim.get("max_duration_s", cb.get("max_duration_s", 600))), notes
    )
    ring = clamp_limit(
        "ring_duration_ms",
        float(lim.get("ring_duration_ms", cb.get("ring_duration_ms", 5000))),
        notes,
    )
    sensitivity = clamp_limit(
        "interruption_sensitivity", float(cb.get("interruption_sensitivity", 0.9)), notes
    )
    responsiveness = clamp_limit("responsiveness", float(cb.get("responsiveness", 0.8)), notes)

    dtmf_raw: Mapping[str, Any] = adv.get("dtmf") or {}
    dtmf = DtmfConfig(
        enabled=bool(dtmf_raw.get("enabled", False)),
        timeout_ms=int(
            clamp_limit("dtmf.timeout_ms", float(dtmf_raw.get("timeout_ms", 2500)), notes)
        ),
        termination_key=dtmf_raw.get("termination_key", "#"),
        digits=int(clamp_limit("dtmf.digits", float(dtmf_raw.get("digits", 10)), notes)),
    )
    vm_raw: Mapping[str, Any] = adv.get("voicemail_detection") or {}
    message = vm_raw.get("message")
    voicemail = VoicemailConfig(
        enabled=bool(vm_raw.get("enabled", False)),
        action="leave_message" if vm_raw.get("action") == "leave_message" else "hang_up",
        message=str(message)[:500] if message else None,
    )
    return CallBehavior(
        end_on_silence_s=silence,
        max_duration_s=max_duration,
        ring_duration_ms=int(ring),
        interruption=map_interruption(sensitivity),
        endpointing=map_responsiveness(responsiveness),
        dtmf=dtmf,
        voicemail=voicemail,
        notes=tuple(notes),
    )


# --------------------------------------------------------------------------------------------
# Timers (research R9)


class InactivityTimer:
    """Fires after ``timeout_s`` with neither party speaking and no pending work.

    Resets on caller speech start, agent speech start, keypad digit; is suspended while any work
    is pending (reply generation, tool run, either party speaking) and restarts when the last
    piece of work ends.
    """

    def __init__(self, clock: Clock, timeout_s: float, on_fire: Callable[[], None]) -> None:
        self._clock = clock
        self._timeout = timeout_s
        self._on_fire = on_fire
        self._handle: TimerHandle | None = None
        self._busy: set[str] = set()
        self._running = False
        self.fired = False

    @property
    def busy(self) -> frozenset[str]:
        return frozenset(self._busy)

    def start(self) -> None:
        self._running = True
        self._arm()

    def stop(self) -> None:
        self._running = False
        self._cancel()

    def activity(self) -> None:
        """A reset event (speech start, keypad digit)."""
        self._arm()

    def busy_begin(self, reason: str) -> None:
        self._busy.add(reason)
        self._cancel()

    def busy_end(self, reason: str) -> None:
        self._busy.discard(reason)
        self._arm()

    def _cancel(self) -> None:
        if self._handle is not None:
            self._handle.cancel()
            self._handle = None

    def _arm(self) -> None:
        self._cancel()
        if self._running and not self._busy and not self.fired:
            self._handle = self._clock.call_later(self._timeout, self._fire)

    def _fire(self) -> None:
        self._handle = None
        if self._running and not self._busy and not self.fired:
            self.fired = True
            self._on_fire()


class DurationTimer:
    """Fires ``max_duration_s`` after connection (FR-016)."""

    def __init__(self, clock: Clock, max_duration_s: float, on_fire: Callable[[], None]) -> None:
        self._clock = clock
        self._max = max_duration_s
        self._on_fire = on_fire
        self._handle: TimerHandle | None = None
        self.fired = False

    def start(self) -> None:
        self._handle = self._clock.call_later(self._max, self._fire)

    def stop(self) -> None:
        if self._handle is not None:
            self._handle.cancel()
            self._handle = None

    def _fire(self) -> None:
        self._handle = None
        if not self.fired:
            self.fired = True
            self._on_fire()


# --------------------------------------------------------------------------------------------
# Keypad input (research R11)

FlushReason = Literal["termination_key", "digit_limit", "timeout"]
DTMF_DIGITS = frozenset("0123456789*#")


class DtmfCollector:
    """Buffers digits; flushes on termination key, digit limit or pause (FR-021)."""

    def __init__(
        self,
        clock: Clock,
        config: DtmfConfig,
        on_flush: Callable[[str, FlushReason], None],
    ) -> None:
        self._clock = clock
        self._config = config
        self._on_flush = on_flush
        self._digits: list[str] = []
        self._handle: TimerHandle | None = None

    @property
    def pending(self) -> str:
        return "".join(self._digits)

    def add(self, digit: str) -> None:
        if digit not in DTMF_DIGITS:
            raise ValueError(f"invalid keypad digit {digit!r}")
        self._cancel()
        if self._config.termination_key and digit == self._config.termination_key:
            self._flush("termination_key")
            return
        self._digits.append(digit)
        if len(self._digits) >= self._config.digits:
            self._flush("digit_limit")
            return
        self._handle = self._clock.call_later(
            self._config.timeout_ms / 1000.0, lambda: self._flush("timeout")
        )

    def close(self) -> None:
        self._cancel()

    def _cancel(self) -> None:
        if self._handle is not None:
            self._handle.cancel()
            self._handle = None

    def _flush(self, reason: FlushReason) -> None:
        self._cancel()
        digits = "".join(self._digits)
        self._digits.clear()
        if digits:
            self._on_flush(digits, reason)


# --------------------------------------------------------------------------------------------
# Voicemail detection (research R10)

VOICEMAIL_WINDOW_S = 30.0
POST_GREETING_SILENCE_S = 1.5
VOICEMAIL_TOOL_NAME = "report_answering_machine"
VOICEMAIL_INSTRUCTION = (
    "If the audio so far is an answering machine greeting or a voicemail prompt rather than a "
    f"live person, call {VOICEMAIL_TOOL_NAME} immediately and say nothing."
)


class VoicemailHandler:
    """Decides what to do after the LLM reports an answering machine.

    Active for outbound calls with detection on, for the first 30 seconds after answer. For
    ``leave_message`` it waits until the caller side has been silent for 1.5 seconds (the beep is
    followed by silence) and then calls ``speak_message``; for ``hang_up`` it ends at once.
    """

    def __init__(
        self,
        clock: Clock,
        config: VoicemailConfig,
        *,
        hang_up: Callable[[], None],
        speak_message: Callable[[str], None],
    ) -> None:
        self._clock = clock
        self._config = config
        self._hang_up = hang_up
        self._speak = speak_message
        self._answered_at: float | None = None
        self._detected = False
        self._wait: TimerHandle | None = None
        self._caller_speaking = False
        self.message_sent = False

    @property
    def detected(self) -> bool:
        return self._detected

    def answered(self) -> None:
        self._answered_at = self._clock.now()

    def active(self) -> bool:
        if not self._config.enabled or self._answered_at is None or self._detected:
            return False
        return self._clock.now() - self._answered_at <= VOICEMAIL_WINDOW_S

    def report_machine(self) -> bool:
        """Called by the internal tool. Returns False when outside the detection window."""
        if not self.active():
            return False
        self._detected = True
        if self._config.action == "hang_up" or not self._config.message:
            self._hang_up()
        elif not self._caller_speaking:
            self._arm_wait()
        return True

    def caller_speech_started(self) -> None:
        self._caller_speaking = True
        if self._wait is not None:
            self._wait.cancel()
            self._wait = None

    def caller_speech_ended(self) -> None:
        self._caller_speaking = False
        if self._detected and not self.message_sent and self._config.action == "leave_message":
            self._arm_wait()

    def _arm_wait(self) -> None:
        if self._wait is not None:
            self._wait.cancel()
        self._wait = self._clock.call_later(POST_GREETING_SILENCE_S, self._leave_message)

    def _leave_message(self) -> None:
        self._wait = None
        if self.message_sent or not self._config.message:
            return
        self.message_sent = True
        self._speak(self._config.message)
