"""Per-turn latency, usage meters, transcript items and event batching (R6, R7).

The worker reports everything as ``CallEvent`` dicts (``contracts/call_events.yaml``) posted to
``POST /v1/internal/calls/{call_id}/events``. Posting is async and off the audio path; every post
is also the heartbeat (at least every ``heartbeat_interval_s``) and its response may order the
call ended (``control.action == "end_call"``).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal, Protocol

from worker.internal_api import (
    MAX_EVENTS_PER_BATCH,
    CallClosed,
    EventBatchResult,
    InternalApiError,
)

log = logging.getLogger("callwright.worker.metrics")

Event = dict[str, Any]


def _ms(seconds: float | None) -> int | None:
    return None if seconds is None else round(seconds * 1000)


# --------------------------------------------------------------------------------------------
# Usage meters (cumulative per component, provider and model)


@dataclass
class UsageMeters:
    """Cumulative counters since call start, keyed by (provider, model) per component."""

    stt: dict[tuple[str, str], int] = field(default_factory=dict)
    llm: dict[tuple[str, str], dict[str, int]] = field(default_factory=dict)
    tts: dict[tuple[str, str | None], int] = field(default_factory=dict)
    nc: dict[tuple[str, str], int] = field(default_factory=dict)

    def add_stt(self, provider: str, model: str, audio_ms: float) -> None:
        key = (provider, model)
        self.stt[key] = self.stt.get(key, 0) + max(0, round(audio_ms))

    def add_llm(
        self,
        provider: str,
        model: str,
        *,
        input_tokens: int = 0,
        cached_input_tokens: int = 0,
        output_tokens: int = 0,
    ) -> None:
        row = self.llm.setdefault(
            (provider, model),
            {"input_tokens": 0, "cached_input_tokens": 0, "output_tokens": 0},
        )
        row["input_tokens"] += max(0, input_tokens)
        row["cached_input_tokens"] += max(0, cached_input_tokens)
        row["output_tokens"] += max(0, output_tokens)

    def add_tts(self, provider: str, model: str | None, characters: int) -> None:
        key = (provider, model)
        self.tts[key] = self.tts.get(key, 0) + max(0, characters)

    def add_nc(self, provider: str, model: str, audio_ms: float) -> None:
        if provider == "none":
            return
        key = (provider, model)
        self.nc[key] = self.nc.get(key, 0) + max(0, round(audio_ms))

    def set_nc(self, provider: str, model: str, audio_ms: float) -> None:
        """Noise cancellation processes all caller audio: the meter is the connected time.

        Never lowers a counter, so snapshots stay monotonic (R7).
        """
        if provider == "none":
            return
        key = (provider, model)
        self.nc[key] = max(self.nc.get(key, 0), max(0, round(audio_ms)))

    def snapshot(self) -> dict[str, list[dict[str, Any]]]:
        """Contract ``UsageSnapshot``."""
        return {
            "stt": [{"provider": p, "model": m, "audio_ms": v} for (p, m), v in self.stt.items()],
            "llm": [{"provider": p, "model": m, **dict(v)} for (p, m), v in self.llm.items()],
            "tts": [{"provider": p, "model": m, "characters": v} for (p, m), v in self.tts.items()],
            "nc": [{"provider": p, "model": m, "audio_ms": v} for (p, m), v in self.nc.items()],
        }


# --------------------------------------------------------------------------------------------
# Turn latency


@dataclass
class TurnRecord:
    turn_index: int
    user_end_of_speech_at: float | None = None
    agent_first_audio_at: float | None = None
    stt_final_ms: int | None = None
    eou_delay_ms: int | None = None
    llm_ttft_ms: int | None = None
    tts_ttfb_ms: int | None = None
    tool_ms: int | None = None
    e2e_ms: int | None = None
    interrupted: bool = False
    text: str = ""
    played_text: str = ""


class LatencyTracker:
    """Measures ``e2e_ms`` directly: first agent audio minus caller end of speech (R6).

    Turn 0 is the opening line; its ``e2e_ms`` holds the greeting latency (connection to first
    agent audio). Component metrics are attached to the turn currently being generated.
    """

    def __init__(self) -> None:
        self._next_index = 0
        self._connected_at: float | None = None
        self._pending_eos: float | None = None
        self.current: TurnRecord | None = None
        self.greeting_done = False

    def connected(self, at: float) -> None:
        self._connected_at = at

    def user_speech_ended(self, at: float) -> None:
        self._pending_eos = at

    def begin_turn(self, *, greeting: bool = False) -> TurnRecord:
        if greeting:
            index = 0
            eos = self._connected_at
        else:
            index = max(1, self._next_index)
            eos = self._pending_eos
        self._next_index = index + 1
        self._pending_eos = None
        self.current = TurnRecord(turn_index=index, user_end_of_speech_at=eos)
        return self.current

    def component(self, name: str, seconds: float | None) -> None:
        if self.current is None or seconds is None:
            return
        value = _ms(seconds)
        if name == "stt_final":
            self.current.stt_final_ms = value
        elif name == "eou_delay":
            self.current.eou_delay_ms = value
        elif name == "llm_ttft" and self.current.llm_ttft_ms is None:
            self.current.llm_ttft_ms = value  # first generation of the turn
        elif name == "tts_ttfb" and self.current.tts_ttfb_ms is None:
            self.current.tts_ttfb_ms = value
        elif name == "tool":
            self.current.tool_ms = (self.current.tool_ms or 0) + (value or 0)

    def agent_audio_started(self, at: float) -> TurnRecord | None:
        turn = self.current
        if turn is None or turn.agent_first_audio_at is not None:
            return None
        turn.agent_first_audio_at = at
        if turn.user_end_of_speech_at is not None:
            turn.e2e_ms = _ms(at - turn.user_end_of_speech_at)
        if turn.turn_index == 0:
            self.greeting_done = True
        return turn


def played_words(text: str, fraction: float) -> str:
    """Truncate an interrupted agent turn to the words actually played (FR-012)."""
    words = text.split()
    if fraction >= 1.0:
        return text
    count = max(0, int(len(words) * max(0.0, fraction)))
    return " ".join(words[:count])


# --------------------------------------------------------------------------------------------
# Framework metrics to turn components and meters


class CurrentModels(Protocol):
    def __call__(self, kind: Literal["stt", "llm", "tts"]) -> tuple[str, str | None]: ...


class MetricsBridge:
    """Maps livekit-agents ``metrics_collected`` payloads onto the tracker and meters (R6, R7).

    ``EOUMetrics`` gives ``stt_final_ms`` (``transcription_delay``) and ``eou_delay_ms``
    (``end_of_utterance_delay``); ``LLMMetrics`` gives ``llm_ttft_ms`` and token meters;
    ``TTSMetrics`` gives ``tts_ttfb_ms``; ``STTMetrics`` gives streamed audio. TTS characters
    are metered in the agent's TTS node after pronunciation replacement, not from metrics.
    ``models`` returns the current (provider, model) per kind so meters follow overrides.
    """

    def __init__(self, tracker: LatencyTracker, meters: UsageMeters, models: CurrentModels):
        self._tracker = tracker
        self._meters = meters
        self._models = models

    def on_metrics(self, metrics: Any) -> None:
        kind = getattr(metrics, "type", None)
        if kind == "eou_metrics":
            self._tracker.component("stt_final", metrics.transcription_delay)
            self._tracker.component("eou_delay", metrics.end_of_utterance_delay)
        elif kind == "llm_metrics":
            if metrics.ttft is not None and metrics.ttft >= 0 and not metrics.cancelled:
                self._tracker.component("llm_ttft", metrics.ttft)
            provider, model = self._models("llm")
            self._meters.add_llm(
                provider,
                model or "",
                input_tokens=metrics.prompt_tokens,
                cached_input_tokens=metrics.prompt_cached_tokens,
                output_tokens=metrics.completion_tokens,
            )
        elif kind == "tts_metrics":
            if metrics.ttfb is not None and metrics.ttfb >= 0:
                self._tracker.component("tts_ttfb", metrics.ttfb)
        elif kind == "stt_metrics":
            provider, model = self._models("stt")
            self._meters.add_stt(provider, model or "", metrics.audio_duration * 1000.0)


# --------------------------------------------------------------------------------------------
# Event recorder


class WallClock(Protocol):
    def __call__(self) -> datetime: ...


def utc_now() -> datetime:
    return datetime.now(UTC)


class EventRecorder:
    """Builds contract events with strictly increasing ``seq`` and queues them for posting."""

    def __init__(
        self,
        meters: UsageMeters | None = None,
        *,
        wall_clock: Callable[[], datetime] = utc_now,
        monotonic: Callable[[], float] | None = None,
    ) -> None:
        self.meters = meters or UsageMeters()
        self._wall = wall_clock
        self._mono = monotonic
        self._seq = 0
        self._queue: list[Event] = []
        self._connected_mono: float | None = None
        self.history: list[Event] = []

    @property
    def seq(self) -> int:
        return self._seq

    def connected(self) -> None:
        if self._mono is not None:
            self._connected_mono = self._mono()

    def offset_ms(self, at: float | None = None) -> int | None:
        if self._connected_mono is None or self._mono is None:
            return None
        ref = self._mono() if at is None else at
        return max(0, round((ref - self._connected_mono) * 1000))

    def _emit(self, type_: str, body: dict[str, Any], at: float | None = None) -> Event:
        self._seq += 1
        event: Event = {
            "seq": self._seq,
            "type": type_,
            "occurred_at": self._wall().isoformat(),
            "offset_ms": self.offset_ms(at),
            **body,
        }
        self._queue.append(event)
        self.history.append(event)
        return event

    def status(
        self,
        status: Literal["ringing", "in_progress", "ended", "no_answer", "busy", "failed"],
        *,
        disconnect_reason: str | None = None,
        diagnostic: str | None = None,
        sip_status_code: int | None = None,
    ) -> Event:
        body: dict[str, Any] = {"status": status}
        if disconnect_reason:
            body["disconnect_reason"] = disconnect_reason
        if diagnostic:
            body["diagnostic"] = diagnostic
        if sip_status_code is not None:
            body["sip_status_code"] = sip_status_code
        return self._emit("status", body)

    def turn(self, record: TurnRecord) -> Event:
        return self._emit(
            "turn",
            {
                "turn_index": record.turn_index,
                "stt_final_ms": record.stt_final_ms,
                "eou_delay_ms": record.eou_delay_ms,
                "llm_ttft_ms": record.llm_ttft_ms,
                "tts_ttfb_ms": record.tts_ttfb_ms,
                "e2e_ms": record.e2e_ms,
                "tool_ms": record.tool_ms,
                "interrupted": record.interrupted,
            },
        )

    def transcript_item(self, item: dict[str, Any]) -> Event:
        return self._emit("transcript_item", {"item": item})

    def message(
        self,
        role: Literal["user", "agent"],
        text: str,
        *,
        started_ms: int | None,
        ended_ms: int | None,
        turn_index: int | None = None,
        interrupted: bool | None = None,
        confidence: float | None = None,
        source: Literal["voice", "keypad"] | None = None,
    ) -> Event:
        item: dict[str, Any] = {"type": "message", "role": role, "text": text}
        for key, value in (
            ("started_ms", started_ms),
            ("ended_ms", ended_ms),
            ("turn_index", turn_index),
            ("interrupted", interrupted),
            ("confidence", confidence),
            ("source", source),
        ):
            if value is not None:
                item[key] = value
        return self.transcript_item(item)

    def system(self, event: str, detail: str | None = None) -> Event:
        item: dict[str, Any] = {"type": "system", "event": event}
        if detail:
            item["detail"] = detail[:2000]
        at = self.offset_ms()
        if at is not None:
            item["at_ms"] = at
        return self.transcript_item(item)

    def usage(self) -> Event:
        return self._emit("usage", {"usage": self.meters.snapshot()})

    def tool_call(
        self,
        name: str,
        *,
        ref: str | None = None,
        arguments: dict[str, Any] | None = None,
        output: str | None = None,
        is_error: bool | None = None,
        duration_ms: int | None = None,
    ) -> Event:
        body: dict[str, Any] = {"name": name}
        for key, value in (
            ("ref", ref),
            ("arguments", arguments),
            ("output", output[:8192] if output is not None else None),
            ("is_error", is_error),
            ("duration_ms", duration_ms),
        ):
            if value is not None:
                body[key] = value
        return self._emit("tool_call", body)

    def flow_transition(
        self, to_node_id: str, from_node_id: str | None, label: str | None
    ) -> Event:
        body: dict[str, Any] = {"to_node_id": to_node_id, "from_node_id": from_node_id}
        if label:
            body["label"] = label
        return self._emit("flow_transition", body)

    def dtmf(
        self,
        digits: str,
        direction: Literal["received", "sent"],
        flush_reason: str | None = None,
    ) -> Event:
        body: dict[str, Any] = {"digits": digits, "direction": direction}
        if flush_reason:
            body["flush_reason"] = flush_reason
        return self._emit("dtmf", body)

    def warning(
        self,
        code: str,
        *,
        component: str | None = None,
        provider: str | None = None,
        detail: str | None = None,
        level: Literal["warning", "error"] = "warning",
    ) -> Event:
        body: dict[str, Any] = {"code": code}
        if component:
            body["component"] = component
        if provider:
            body["provider"] = provider
        if detail:
            body["detail"] = detail[:2000]
        return self._emit(level, body)

    def drain(self, limit: int = MAX_EVENTS_PER_BATCH) -> list[Event]:
        batch, self._queue = self._queue[:limit], self._queue[limit:]
        return batch

    def requeue(self, batch: Sequence[Event]) -> None:
        self._queue = list(batch) + self._queue

    @property
    def pending(self) -> int:
        return len(self._queue)


# --------------------------------------------------------------------------------------------
# Posting


class EventSink(Protocol):
    async def post_events(
        self, call_id: str, events: Sequence[dict[str, Any]]
    ) -> EventBatchResult: ...


EndCallHandler = Callable[[str], Awaitable[None] | None]


class EventPoster:
    """Posts queued events in batches; an empty batch is the heartbeat.

    A usage snapshot is appended to every batch so the API's running-cost check sees current
    meters (R3, R7). An ``end_call`` control in any response calls ``on_end_call(reason)`` once.
    """

    def __init__(
        self,
        call_id: str,
        recorder: EventRecorder,
        sink: EventSink,
        *,
        on_end_call: EndCallHandler,
        interval_s: float = 10.0,
        before_flush: Callable[[], None] | None = None,
    ) -> None:
        self.call_id = call_id
        self._recorder = recorder
        self._sink = sink
        self._on_end_call = on_end_call
        self._interval = interval_s
        self._before_flush = before_flush
        self._task: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()
        self.closed = False
        self.end_call_requested: str | None = None
        self.posts = 0

    async def flush(self, *, with_usage: bool = True) -> EventBatchResult | None:
        """Post everything queued (in batches of 200). Returns the last result."""
        if self.closed:
            return None
        async with self._lock:
            if self._before_flush is not None:
                self._before_flush()
            if with_usage:
                self._recorder.usage()
            result: EventBatchResult | None = None
            while True:
                batch = self._recorder.drain()
                try:
                    result = await self._sink.post_events(self.call_id, batch)
                except CallClosed:
                    self.closed = True
                    return None
                except InternalApiError as exc:
                    log.warning("events post failed for %s: %s", self.call_id, exc)
                    self._recorder.requeue(batch)
                    return None
                self.posts += 1
                await self._handle_control(result)
                if self._recorder.pending == 0:
                    return result

    async def _handle_control(self, result: EventBatchResult) -> None:
        if result.control.action != "end_call" or self.end_call_requested:
            return
        reason = result.control.disconnect_reason or "error"
        self.end_call_requested = reason
        maybe = self._on_end_call(reason)
        if maybe is not None:
            await maybe

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name=f"events:{self.call_id}")

    async def _run(self) -> None:
        while not self.closed:
            await asyncio.sleep(self._interval)
            await self.flush()

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        await self.flush()
