"""Sanas NC adapter (T037): engine contract, pass-through default, fake engine, metering."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import numpy as np
import pytest
from livekit import rtc

from tests.harness.fakes import FakeSanasEngine
from tests.unit.test_live_call import live_call
from worker.adapters.nc import sanas
from worker.adapters.registry import AdapterRegistry, VendorSpec
from worker.settings import WorkerSettings

RATE = 48000
FRAME = RATE // 100  # 10 ms
SPEC = VendorSpec("nc", "sanas", "vi")


@pytest.fixture(autouse=True)
def no_engine() -> Iterator[None]:
    sanas.register_engine(None)
    yield
    sanas.register_engine(None)


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
    processor = sanas.build(SPEC, creds())
    is_frame_processor = isinstance(processor, rtc.FrameProcessor)
    assert is_frame_processor
    assert processor.mode == "voice_isolation"
    assert not processor.applied and processor.passthrough_reason == "sanas_sdk_unavailable"
    audio, _ = noisy_call_audio()
    assert np.array_equal(run_frames(processor, audio), audio)
    assert processor.processed_ms == 0.0


def test_registered_engine_needs_a_key() -> None:
    sanas.register_engine(lambda mode, config: FakeSanasEngine(mode))
    processor = sanas.build(VendorSpec("nc", "sanas", "st"), {})
    assert processor.passthrough_reason == "sanas_api_key_missing"
    assert processor.mode == "standard"


def test_fake_engine_lowers_noise_floor_and_keeps_speech() -> None:
    seen: list[tuple[str, sanas.SanasConfig]] = []

    def factory(mode: str, config: sanas.SanasConfig) -> FakeSanasEngine:
        seen.append((mode, config))
        return FakeSanasEngine(mode)

    sanas.register_engine(factory)
    processor = AdapterRegistry().build(SPEC, creds())
    assert processor.applied and processor.passthrough_reason is None
    assert seen[0][0] == "voice_isolation" and seen[0][1].api_key == "sk-test"
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

    sanas.register_engine(lambda mode, config: Broken(mode))
    processor = sanas.build(SPEC, creds())
    audio, _ = noisy_call_audio()
    assert np.array_equal(run_frames(processor, audio), audio)
    assert processor.errors == 300 and processor.processed_ms == 0.0


def test_disabled_filter_bypasses_engine() -> None:
    engine = FakeSanasEngine("voice_isolation")
    sanas.register_engine(lambda mode, config: engine)
    processor = sanas.build(SPEC, creds())
    processor.enabled = False
    audio, _ = noisy_call_audio()
    assert np.array_equal(run_frames(processor, audio), audio)
    assert engine.calls == 0


def test_live_call_meters_only_applied_audio_and_warns_on_passthrough() -> None:
    call, _, _ = live_call()
    assert call.plan is not None and call.plan.nc.provider == "sanas"
    call.connected_at = 0.0  # an hour "connected": connected time must not be billed
    call.components = type("C", (), {"nc": sanas.build(SPEC, creds())})()
    call._update_time_meters()
    assert call.meters.snapshot()["nc"] == []
    call._warn_nc_passthrough(call.plan)
    (warning,) = [e for e in call.recorder.drain() if e["type"] == "warning"]
    assert warning["code"] == "nc_passthrough" and warning["component"] == "nc"
    assert warning["provider"] == "sanas" and "sanas_sdk_unavailable" in warning["detail"]

    sanas.register_engine(lambda mode, config: FakeSanasEngine(mode))
    applied = sanas.build(SPEC, creds())
    run_frames(applied, noisy_call_audio()[0])
    call.components = type("C", (), {"nc": applied})()
    call._update_time_meters()
    assert call.meters.snapshot()["nc"] == [{"provider": "sanas", "model": "vi", "audio_ms": 3000}]
    call._warn_nc_passthrough(call.plan)
    assert not [e for e in call.recorder.drain() if e["type"] == "warning"]
