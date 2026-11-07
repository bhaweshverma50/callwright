"""Sanas noise cancellation (models ``vi`` voice isolation and ``st`` standard).

No LiveKit plugin exists (research R8), so the adapter is a frame processor on the caller's
input track (``room_io.AudioInputOptions.noise_cancellation``) that hands each PCM frame to a
:class:`SanasEngine` before speech recognition (FR-020).

Engine contract (what the vendor SDK integration implements and registers with
:func:`register_engine`):

- ``process(samples, sample_rate, num_channels)`` takes interleaved int16 samples for one
  frame (10 ms at the track rate, usually 48 kHz mono) and returns the same number of int16
  samples. It is called synchronously on the audio path, so it must return within the frame
  budget (``MAX_LATENCY_MS``); it resamples itself if the model needs a fixed rate, and keeps
  its streaming state between calls.
- ``applied`` is True when the engine really transforms audio. Only applied audio is metered
  (``usage.nc`` audio_ms, FR-029), so a pass-through never bills the customer.
- ``close()`` releases the stream at call end.

``SANAS_API_KEY`` (``WorkerSettings``) is the account key; without it the pass-through engine
is used. Frames over the per-frame budget are counted in ``slow_frames`` (a health signal for
the integration). A frame whose ``process`` raises or returns the wrong length passes through
unchanged (fail open, the caller is never muted) and is counted in ``errors``.

No vendor SDK or key is available yet, so :func:`make_engine` returns
:class:`PassthroughEngine` unless an engine factory is registered: the call runs, the caller's
audio reaches STT unchanged, nothing is metered and the worker records an ``nc_passthrough``
warning event. Wiring the SDK means one module that calls ``register_engine(factory)`` at
import (from ``worker/adapters/nc/__init__.py`` or a plugin entry point).
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from functools import cache
from typing import Any, Protocol

import numpy as np
import numpy.typing as npt

from worker.adapters.registry import VendorSpec

MODELS = {"vi": "voice_isolation", "st": "standard"}
MAX_LATENCY_MS = 20.0

Samples = npt.NDArray[np.int16]


@dataclass(frozen=True)
class SanasConfig:
    """What the engine factory gets from ``creds``."""

    api_key: str = field(default="", repr=False)  # never in logs or reprs

    @classmethod
    def from_creds(cls, creds: Mapping[str, str]) -> SanasConfig:
        return cls(api_key=creds.get("api_key", ""))


class SanasEngine(Protocol):
    @property
    def applied(self) -> bool: ...

    def process(self, samples: Samples, sample_rate: int, num_channels: int) -> Samples: ...

    def close(self) -> None: ...


class PassthroughEngine:
    """Used when no Sanas SDK is registered or no key is configured."""

    applied = False

    def __init__(self, reason: str) -> None:
        self.reason = reason

    def process(self, samples: Samples, sample_rate: int, num_channels: int) -> Samples:
        return samples

    def close(self) -> None:
        return None


EngineFactory = Callable[[str, SanasConfig], SanasEngine]
_factory: EngineFactory | None = None


def register_engine(factory: EngineFactory | None) -> None:
    """Install the vendor SDK engine factory ``(mode, config) -> SanasEngine`` (None removes)."""
    global _factory
    _factory = factory


def make_engine(mode: str, config: SanasConfig) -> SanasEngine:
    if _factory is None:
        return PassthroughEngine("sanas_sdk_unavailable")
    if not config.api_key:
        return PassthroughEngine("sanas_api_key_missing")
    return _factory(mode, config)


def processor_class() -> type[Any]:
    """``SanasNoiseFilter`` (built lazily so pure tests never import LiveKit)."""
    return _processor_class()


@cache
def _processor_class() -> type[Any]:
    from livekit import rtc

    class SanasNoiseFilter(rtc.FrameProcessor[rtc.AudioFrame]):
        def __init__(self, mode: str, engine: SanasEngine, config: SanasConfig) -> None:
            self.mode = mode
            self.engine = engine
            self.config = config
            self.processed_ms = 0.0
            self.frames = 0
            self.errors = 0
            self.slow_frames = 0
            self._enabled = True

        @property
        def enabled(self) -> bool:
            return self._enabled

        @enabled.setter
        def enabled(self, value: bool) -> None:
            self._enabled = value

        @property
        def applied(self) -> bool:
            return bool(self.engine.applied)

        @property
        def passthrough_reason(self) -> str | None:
            return getattr(self.engine, "reason", None) if not self.applied else None

        def _process(self, frame: rtc.AudioFrame) -> rtc.AudioFrame:
            self.frames += 1
            if not self._enabled or not self.engine.applied:
                return frame
            samples = np.frombuffer(frame.data, dtype=np.int16)
            started = time.perf_counter()
            try:
                out = self.engine.process(samples, frame.sample_rate, frame.num_channels)
            except Exception:
                self.errors += 1
                return frame
            if (time.perf_counter() - started) * 1000.0 > MAX_LATENCY_MS:
                self.slow_frames += 1
            if out.shape != samples.shape:
                self.errors += 1
                return frame
            self.processed_ms += frame.duration * 1000.0
            return rtc.AudioFrame(
                out.astype(np.int16, copy=False).tobytes(),
                frame.sample_rate,
                frame.num_channels,
                frame.samples_per_channel,
            )

        def _close(self) -> None:
            self._enabled = False
            self.engine.close()

    return SanasNoiseFilter


def build(spec: VendorSpec, creds: Mapping[str, str]) -> Any:
    mode = MODELS[spec.required_model]
    config = SanasConfig.from_creds(creds)
    return processor_class()(mode, make_engine(mode, config), config)
