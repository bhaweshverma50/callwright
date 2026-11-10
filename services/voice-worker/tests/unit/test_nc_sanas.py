"""Sanas NC adapter (T037): pass-through default, and a fake engine behind the frame filter."""

from __future__ import annotations

from typing import Any

import numpy as np
import pytest
from livekit import rtc

from tests.harness.fakes import FakeSanasEngine
from worker.adapters.nc import sanas
from worker.adapters.registry import AdapterRegistry, VendorSpec
from worker.settings import WorkerSettings

RATE = 48000
FRAME = RATE // 100  # 10 ms
SPEC = VendorSpec("nc", "sanas", "vi")


def noisy_call_audio(seed: int = 7) -> tuple[np.ndarray[Any, Any], np.ndarray[Any, Any]]:
    """1 s noise, 1 s 'speech' (220 Hz tone at -12 dBFS) over the noise, 1 s noise."""
    rng = np.random.default_rng(seed)
    noise = rng.normal(0.0, 150.0, 3 * RATE)
    t = np.arange(RATE) / RATE
    signal = noise.copy()
    signal[RATE : 2 * RATE] += 8000 * np.sin(2 * np.pi * 220 * t)
    is_speech = np.zeros(3 * RATE, dtype=bool)
    is_speech[RATE : 2 * RATE] = True
    return np.clip(signal, -32768, 32767).astype(np.int16), is_speech


def run_frames(processor: Any, audio: np.ndarray[Any, Any]) -> np.ndarray[Any, Any]:
    out = []
    for start in range(0, len(audio), FRAME):
        chunk = audio[start : start + FRAME]
        frame = rtc.AudioFrame(chunk.tobytes(), RATE, 1, len(chunk))
        result = processor._process(frame)
        out.append(np.frombuffer(result.data, dtype=np.int16))
    return np.concatenate(out)


def rms_db(x: np.ndarray[Any, Any]) -> float:
    return 20 * float(np.log10(np.sqrt(np.mean(x.astype(np.float64) ** 2)) + 1e-9))


def creds(**extra: str) -> dict[str, str]:
    return {"api_key": "sk-test", **extra}


def test_settings_carry_the_sanas_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SANAS_API_KEY", "k")
    config = sanas.SanasConfig.from_creds(WorkerSettings().vendor_credentials()["sanas"])
    assert config == sanas.SanasConfig("k")
    assert sanas.SanasConfig.from_creds({}) == sanas.SanasConfig()
    assert "sk-secret-123" not in repr(sanas.SanasConfig(api_key="sk-secret-123"))


def test_passthrough_without_sdk_is_identity_and_unmetered() -> None:
    processor = AdapterRegistry().build(SPEC, creds())
    is_frame_processor = isinstance(processor, rtc.FrameProcessor)
    assert is_frame_processor
    assert processor.mode == "voice_isolation"
    assert not processor.applied and processor.passthrough_reason == "sanas_sdk_unavailable"
    audio, _ = noisy_call_audio()
    assert np.array_equal(run_frames(processor, audio), audio)
    assert processor.processed_ms == 0.0


def filter_with(engine: Any) -> Any:
    return sanas.processor_class()("voice_isolation", engine, sanas.SanasConfig("sk-test"))


def test_fake_engine_lowers_noise_floor_and_keeps_speech() -> None:
    processor = filter_with(FakeSanasEngine("voice_isolation"))
    assert processor.applied and processor.passthrough_reason is None
    audio, is_speech = noisy_call_audio()
    out = run_frames(processor, audio)
    assert out.shape == audio.shape
    noise_drop = rms_db(audio[~is_speech]) - rms_db(out[~is_speech])
    speech_change = abs(rms_db(audio[is_speech]) - rms_db(out[is_speech]))
    assert noise_drop >= 25.0
    assert speech_change < 0.5
    assert processor.processed_ms == pytest.approx(3000.0)
    processor._close()
    assert processor.engine.closed and not processor.enabled


def test_engine_failure_fails_open() -> None:
    class Broken(FakeSanasEngine):
        def process(self, samples: Any, sample_rate: int, num_channels: int) -> Any:
            self.calls += 1
            if self.calls % 2:
                raise RuntimeError("engine down")
            return samples[:-1]  # wrong length

    processor = filter_with(Broken("voice_isolation"))
    audio, _ = noisy_call_audio()
    assert np.array_equal(run_frames(processor, audio), audio)
    assert processor.errors == 300 and processor.processed_ms == 0.0


def test_disabled_filter_bypasses_engine() -> None:
    engine = FakeSanasEngine("voice_isolation")
    processor = filter_with(engine)
    processor.enabled = False
    audio, _ = noisy_call_audio()
    assert np.array_equal(run_frames(processor, audio), audio)
    assert engine.calls == 0
