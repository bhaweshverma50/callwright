"""livekit-agents compatible fake vendors for the live benchmark (no network, no keys).

They run inside the real ``AgentSession`` on a real LiveKit room, so the transport, Silero VAD,
the semantic turn detector, preemptive generation, the TTS stream adapter and room audio
output are all the production code. Only the vendor round trips are simulated, with delays
sampled from the call set's log-normal profiles (the same profiles as fake mode):

- :class:`EnergySTT`: streaming STT. Detects caller speech by frame energy, and emits the
  final transcript ``stt_final_ms`` after the last voiced frame. Transcripts come from the
  scripted turn list, in order.
- :func:`delayed_llm`: streams a fixed reply after ``llm_ttft_ms``.
- :class:`ToneTTS`: non-streaming TTS that returns voiced audio (harmonics with a syllable
  envelope, ``ms_per_char`` long) after ``tts_ttfb_ms``.

Noise cancellation uses the real adapter from the agent config (Sanas runs as its
pass-through engine until the SDK is wired).
"""

from __future__ import annotations

import asyncio
import contextlib
import importlib
import math
import random
import time
import uuid
from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from livekit import rtc
from livekit.agents import LanguageCode, llm, stt, tts
from livekit.agents.types import (
    DEFAULT_API_CONNECT_OPTIONS,
    NOT_GIVEN,
    APIConnectOptions,
    NotGivenOr,
)
from livekit.agents.utils import AudioBuffer

from worker.adapters.registry import AdapterRegistry, VendorSpec

Z95 = 1.6449
TTS_SAMPLE_RATE = 24000


@dataclass
class LiveFakeParams:
    """Per-call fake vendor behaviour, carried in the dispatch metadata (``bench`` key)."""

    turns: list[str]
    profile: dict[str, dict[str, float]]
    seed: int = 0
    reply: str = "Sure, I can help with that."
    ms_per_char: float = 45.0
    speech_rms: float = 400.0
    hangover_ms: float = 120.0

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> LiveFakeParams:
        return cls(
            turns=list(data.get("turns") or []),
            profile={k: dict(v) for k, v in (data.get("profile") or {}).items()},
            seed=int(data.get("seed", 0)),
            reply=str(data.get("reply") or cls.reply),
            ms_per_char=float(data.get("ms_per_char", 45.0)),
            speech_rms=float(data.get("speech_rms", 400.0)),
            hangover_ms=float(data.get("hangover_ms", 120.0)),
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "turns": self.turns,
            "profile": self.profile,
            "seed": self.seed,
            "reply": self.reply,
            "ms_per_char": self.ms_per_char,
            "speech_rms": self.speech_rms,
            "hangover_ms": self.hangover_ms,
        }


@dataclass
class DelaySampler:
    profile: Mapping[str, Mapping[str, float]]
    rng: random.Random = field(default_factory=random.Random)

    def seconds(self, key: str, default_ms: float) -> float:
        row = self.profile.get(key)
        if not row:
            return default_ms / 1000.0
        median = float(row["median"])
        sigma = math.log(float(row["p95"]) / median) / Z95
        return median * math.exp(self.rng.gauss(0.0, sigma)) / 1000.0


def frame_rms(frame: rtc.AudioFrame) -> float:
    data = np.frombuffer(frame.data, dtype=np.int16)
    if data.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(data.astype(np.float64) ** 2)))


# --------------------------------------------------------------------------------------------
# STT


class EnergySTT(stt.STT):  # type: ignore[type-arg]
    def __init__(self, spec: VendorSpec, params: LiveFakeParams, sampler: DelaySampler) -> None:
        super().__init__(capabilities=stt.STTCapabilities(streaming=True, interim_results=False))
        self.spec = spec
        self.params = params
        self.sampler = sampler
        self.transcripts: deque[str] = deque(params.turns)

    @property
    def model(self) -> str:
        return self.spec.model or "fake"

    @property
    def provider(self) -> str:
        return self.spec.provider

    def next_transcript(self) -> str:
        return self.transcripts.popleft() if self.transcripts else "Hello?"

    async def _recognize_impl(
        self,
        buffer: AudioBuffer,
        *,
        language: NotGivenOr[str] = NOT_GIVEN,
        conn_options: APIConnectOptions,
    ) -> stt.SpeechEvent:
        return _final(self.next_transcript(), self._language())

    def _language(self) -> str:
        return str(self.spec.options.get("language") or "en")

    def stream(
        self,
        *,
        language: NotGivenOr[str] = NOT_GIVEN,
        conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS,
    ) -> stt.RecognizeStream:
        return EnergyStream(stt=self, conn_options=conn_options)


def _final(text: str, language: str) -> stt.SpeechEvent:
    return stt.SpeechEvent(
        type=stt.SpeechEventType.FINAL_TRANSCRIPT,
        request_id=uuid.uuid4().hex[:12],
        alternatives=[stt.SpeechData(language=LanguageCode(language), text=text, confidence=0.95)],
    )


class EnergyStream(stt.RecognizeStream):
    def __init__(self, *, stt: EnergySTT, conn_options: APIConnectOptions) -> None:
        super().__init__(stt=stt, conn_options=conn_options)
        self._fake = stt
        self._pending: set[asyncio.Task[None]] = set()

    async def _run(self) -> None:
        params = self._fake.params
        speaking = False
        speech_started = 0.0
        last_voiced = 0.0
        silence_ms = 0.0
        try:
            async for item in self._input_ch:
                if not isinstance(item, rtc.AudioFrame):
                    continue
                now = time.time()
                duration_ms = item.duration * 1000.0
                if frame_rms(item) >= params.speech_rms:
                    if not speaking:
                        speaking = True
                        speech_started = now - item.duration
                        self._event_ch.send_nowait(
                            stt.SpeechEvent(
                                type=stt.SpeechEventType.START_OF_SPEECH,
                                speech_start_time=speech_started,
                            )
                        )
                    last_voiced = now
                    silence_ms = 0.0
                elif speaking:
                    silence_ms += duration_ms
                    if silence_ms >= params.hangover_ms:
                        speaking = False
                        self._schedule_final(speech_started, last_voiced)
        finally:
            for task in list(self._pending):
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task

    def _schedule_final(self, started: float, ended: float) -> None:
        delay = self._fake.sampler.seconds("stt_final_ms", 160.0)
        text = self._fake.next_transcript()

        async def emit() -> None:
            await asyncio.sleep(max(0.0, ended + delay - time.time()))
            event = _final(text, self._fake._language())
            self._event_ch.send_nowait(event)
            self._event_ch.send_nowait(
                stt.SpeechEvent(type=stt.SpeechEventType.END_OF_SPEECH, speech_end_time=ended)
            )
            self._event_ch.send_nowait(
                stt.SpeechEvent(
                    type=stt.SpeechEventType.RECOGNITION_USAGE,
                    recognition_usage=stt.RecognitionUsage(audio_duration=ended - started),
                )
            )

        task = asyncio.create_task(emit())
        self._pending.add(task)
        task.add_done_callback(self._pending.discard)


# --------------------------------------------------------------------------------------------
# LLM


def delayed_llm(spec: VendorSpec, params: LiveFakeParams, sampler: DelaySampler) -> Any:
    class DelayedStream(llm.LLMStream):
        async def _run(self) -> None:
            await asyncio.sleep(sampler.seconds("llm_ttft_ms", 320.0))
            reply = params.reply
            words = reply.split(" ")
            for i, word in enumerate(words):
                delta = word if i == 0 else " " + word
                self._event_ch.send_nowait(
                    llm.ChatChunk(
                        id="bench", delta=llm.ChoiceDelta(role="assistant", content=delta)
                    )
                )
                await asyncio.sleep(0.005)
            self._event_ch.send_nowait(
                llm.ChatChunk(
                    id="bench",
                    usage=llm.CompletionUsage(
                        completion_tokens=max(1, len(reply) // 4),
                        prompt_tokens=200,
                        prompt_cached_tokens=100,
                        total_tokens=200 + max(1, len(reply) // 4),
                    ),
                )
            )

    class DelayedLLM(llm.LLM):  # type: ignore[type-arg]
        @property
        def model(self) -> str:
            return spec.model or "fake"

        @property
        def provider(self) -> str:
            return spec.provider

        def chat(
            self,
            *,
            chat_ctx: Any,
            tools: list[Any] | None = None,
            conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS,
            **_: Any,
        ) -> Any:
            return DelayedStream(
                self, chat_ctx=chat_ctx, tools=tools or [], conn_options=conn_options
            )

    return DelayedLLM()


# --------------------------------------------------------------------------------------------
# TTS


def voiced_audio(text: str, *, ms_per_char: float, rate: int = TTS_SAMPLE_RATE) -> bytes:
    """Harmonic 'voice' with a 4 Hz syllable envelope that never drops to silence."""
    n = max(int(rate * 0.2), int(len(text) * ms_per_char / 1000.0 * rate))
    t = np.arange(n) / rate
    f0 = 180.0
    wave_ = sum(np.sin(2 * np.pi * k * f0 * t) / k for k in range(1, 9))
    envelope = 0.65 + 0.35 * np.sin(2 * np.pi * 4.0 * t)
    ramp = min(n, int(0.01 * rate))
    envelope[:ramp] *= np.linspace(0.3, 1.0, ramp)
    audio = wave_ * envelope
    audio = audio / (np.max(np.abs(audio)) or 1.0) * 0.5
    return np.asarray(audio * 32767, dtype=np.int16).tobytes()


class ToneTTS(tts.TTS):  # type: ignore[type-arg]
    def __init__(self, spec: VendorSpec, params: LiveFakeParams, sampler: DelaySampler) -> None:
        super().__init__(
            capabilities=tts.TTSCapabilities(streaming=False),
            sample_rate=TTS_SAMPLE_RATE,
            num_channels=1,
        )
        self.spec = spec
        self.params = params
        self.sampler = sampler

    @property
    def model(self) -> str:
        return self.spec.model or "fake"

    @property
    def provider(self) -> str:
        return self.spec.provider

    def synthesize(
        self, text: str, *, conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS
    ) -> tts.ChunkedStream:
        return ToneStream(tts=self, input_text=text, conn_options=conn_options)


class ToneStream(tts.ChunkedStream):
    def __init__(self, *, tts: ToneTTS, input_text: str, conn_options: APIConnectOptions):
        super().__init__(tts=tts, input_text=input_text, conn_options=conn_options)
        self._fake = tts

    async def _run(self, output_emitter: tts.AudioEmitter) -> None:
        fake = self._fake
        await asyncio.sleep(fake.sampler.seconds("tts_ttfb_ms", 130.0))
        output_emitter.initialize(
            request_id=uuid.uuid4().hex[:12],
            sample_rate=TTS_SAMPLE_RATE,
            num_channels=1,
            mime_type="audio/pcm",
        )
        output_emitter.push(voiced_audio(self.input_text, ms_per_char=fake.params.ms_per_char))
        output_emitter.flush()


# --------------------------------------------------------------------------------------------
# Registry


def live_registry(params: LiveFakeParams, base: AdapterRegistry | None = None) -> AdapterRegistry:
    """The real registry (catalog, Auto STT, checks) with STT, LLM and TTS swapped for fakes."""
    sampler = DelaySampler(params.profile, random.Random(params.seed))

    def build(spec: VendorSpec, creds: Mapping[str, str]) -> Any:
        if spec.kind == "stt":
            return EnergySTT(spec, params, sampler)
        if spec.kind == "llm":
            return delayed_llm(spec, params, sampler)
        if spec.kind == "tts":
            return ToneTTS(spec, params, sampler)
        module = importlib.import_module(f"worker.adapters.nc.{spec.provider}")
        return module.build(spec, creds)

    return (base or AdapterRegistry()).with_builders(default_builder=build)
