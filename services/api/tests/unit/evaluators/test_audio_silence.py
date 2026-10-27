"""``audio_silence`` with synthetic dual-channel recordings (007 T076, FR-040, research R12)."""

from __future__ import annotations

import io
import wave
from typing import Any

import numpy as np
import pytest

from app.evaluators.audio import FRAME_MS, RecordingUnavailable, decode_levels, find_silences
from app.evaluators.base import RecordingRef
from app.evaluators.builtins.audio_silence import AudioSilence
from tests.unit.evaluators.helpers import context, tools

RATE = 16_000
SETTINGS = {"max_acceptable_silence_ms": 3000, "silence_threshold_db": -40, "min_silence_ms": 1000}


def tone(ms: int, amp: float = 0.3) -> np.ndarray:
    t = np.arange(int(RATE * ms / 1000)) / RATE
    return amp * np.sin(2 * np.pi * 220 * t)


def quiet(ms: int) -> np.ndarray:
    return np.zeros(int(RATE * ms / 1000))


def wav(left: np.ndarray, right: np.ndarray) -> bytes:
    n = max(len(left), len(right))
    stereo = np.zeros((n, 2))
    stereo[: len(left), 0] = left
    stereo[: len(right), 1] = right
    pcm = (stereo * 32767).astype("<i2")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(pcm.tobytes())
    return buf.getvalue()


def silences(left: np.ndarray, right: np.ndarray, **kw: Any) -> list[tuple[int, int]]:
    levels = decode_levels(wav(left, right))
    found = find_silences(levels, threshold_db=-40, min_silence_ms=kw.get("min_silence_ms", 1000))
    return [(s.start_ms, s.duration_ms) for s in found]


def test_decodes_two_parties() -> None:
    levels = decode_levels(wav(tone(1000), quiet(1000)))
    assert levels.shape == (2, 1000 // FRAME_MS)


def test_silence_on_both_channels_is_found() -> None:
    agent = np.concatenate([tone(1000), quiet(4000), tone(1000)])
    caller = quiet(6000)
    out = silences(agent, caller)
    assert (
        len(out) == 1
        and out[0][0] == pytest.approx(1000, abs=40)
        and out[0][1] == pytest.approx(4000, abs=40)
    )


def test_one_channel_quiet_is_not_silence() -> None:
    agent = np.concatenate([tone(1000), quiet(4000), tone(1000)])
    caller = np.concatenate([quiet(1000), tone(4000), quiet(1000)])
    assert silences(agent, caller) == []


def test_short_pause_ignored() -> None:
    agent = np.concatenate([tone(1000), quiet(800), tone(1000)])
    assert silences(agent, quiet(2800)) == []


def test_leading_and_trailing_silence_excluded() -> None:
    agent = np.concatenate([quiet(5000), tone(1000), quiet(5000)])
    assert silences(agent, quiet(11000)) == []


async def test_boundary_3000_ms_passes_and_longer_fails() -> None:
    evaluator = AudioSilence()
    for gap, expected in ((3000, "pass"), (3200, "fail")):
        data = wav(np.concatenate([tone(1000), quiet(gap), tone(1000)]), quiet(gap + 2000))

        async def read(ref: RecordingRef, data: bytes = data) -> np.ndarray:
            return decode_levels(data)

        ctx = context()
        ctx.recording = RecordingRef("recordings/x.wav", "bucket")
        out = await evaluator.evaluate(ctx, SETTINGS, tools(read_levels=read))
        assert out.items[0].verdict == expected, (gap, out.items[0].rationale)
        assert out.items[0].start_ms == pytest.approx(1000, abs=40)
        assert "0:01" in out.items[0].rationale


async def test_no_recording_or_unreadable_is_not_applicable() -> None:
    evaluator = AudioSilence()
    out = await evaluator.evaluate(context(), SETTINGS, tools())
    assert out.items[0].verdict == "not_applicable" and out.items[0].rationale == "no recording"

    async def broken(ref: RecordingRef) -> np.ndarray:
        raise RecordingUnavailable("purged")

    ctx = context()
    ctx.recording = RecordingRef("k", "b")
    out = await evaluator.evaluate(ctx, SETTINGS, tools(read_levels=broken))
    assert out.items[0].verdict == "not_applicable" and "purged" in out.items[0].rationale
    sim = context(origin="simulation")
    sim.recording = RecordingRef("k", "b")
    assert (await evaluator.evaluate(sim, SETTINGS, tools(read_levels=broken))).items[
        0
    ].verdict == "not_applicable"


def test_corrupt_audio_raises_unavailable() -> None:
    with pytest.raises(RecordingUnavailable):
        decode_levels(b"not audio at all")
