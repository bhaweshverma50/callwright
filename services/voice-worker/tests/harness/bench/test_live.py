"""Offline checks for the live benchmark pieces (no LiveKit server needed)."""

from __future__ import annotations

import asyncio
import random
from typing import Any

import httpx
import numpy as np
import yaml
from livekit import rtc
from livekit.agents import stt

from tests.harness.bench import synth
from tests.harness.bench.live import (
    SERVICE_TOKEN,
    AgentAudioMonitor,
    CallResult,
    FakeInternalApi,
    scripted_transcripts,
    summarize,
)
from tests.harness.bench.live_fakes import (
    DelaySampler,
    EnergySTT,
    LiveFakeParams,
    ToneTTS,
    frame_rms,
    live_registry,
)
from tests.harness.runner import load_agent_config
from worker.adapters.registry import VendorSpec

PROFILE: dict[str, dict[str, float]] = {
    "stt_final_ms": {"median": 50, "p95": 60},
    "tts_ttfb_ms": {"median": 20, "p95": 25},
}


def test_committed_fixtures_match_the_generator() -> None:
    callset = yaml.safe_load(synth.CALLSET.read_text())
    for i, text in enumerate(callset["turns"]):
        committed, rate = synth.read_wav(synth.FIXTURES_DIR / synth.fixture_name(i))
        assert rate == synth.SAMPLE_RATE
        regenerated = synth.to_pcm16(synth.synthesize(text))
        assert committed.shape == regenerated.shape
        # Allow last-bit differences between platforms' libm.
        assert int(np.max(np.abs(committed.astype(np.int32) - regenerated))) <= 2
        assert 1.0 < len(committed) / rate < 4.0


def test_synthesized_speech_has_syllable_rhythm() -> None:
    audio = synth.to_pcm16(synth.synthesize("Please send me the payment link."))
    frames = audio[: len(audio) // 160 * 160].reshape(-1, 160).astype(np.float64)
    rms = np.sqrt(np.mean(frames**2, axis=1))
    loud = rms > 1000
    assert loud.mean() > 0.5
    assert np.count_nonzero(np.diff(loud.astype(int)) == 1) >= 3  # several voiced bursts


def params(**kw: Any) -> LiveFakeParams:
    return LiveFakeParams(turns=["first turn", "second turn"], profile=PROFILE, **kw)


async def test_energy_stt_emits_final_after_speech_ends() -> None:
    p = params()
    fake = EnergySTT(VendorSpec("stt", "deepgram", "nova-3"), p, DelaySampler(p.profile))
    stream = fake.stream()
    pcm, rate = synth.read_wav(synth.FIXTURES_DIR / synth.fixture_name(0))
    audio = np.concatenate([np.zeros(rate // 5, np.int16), pcm, np.zeros(rate // 2, np.int16)])
    step = rate // 100
    for start in range(0, len(audio) - step + 1, step):
        stream.push_frame(rtc.AudioFrame(audio[start : start + step].tobytes(), rate, 1, step))
        await asyncio.sleep(0)
    await asyncio.sleep(0.2)
    stream.end_input()
    events = [ev async for ev in stream]
    kinds = [ev.type for ev in events]
    assert kinds[0] == stt.SpeechEventType.START_OF_SPEECH
    finals = [ev for ev in events if ev.type == stt.SpeechEventType.FINAL_TRANSCRIPT]
    assert [ev.alternatives[0].text for ev in finals] == ["first turn"]
    assert stt.SpeechEventType.END_OF_SPEECH in kinds
    usage = [ev for ev in events if ev.type == stt.SpeechEventType.RECOGNITION_USAGE]
    assert usage and usage[0].recognition_usage is not None


async def test_tone_tts_returns_loud_audio_of_text_length() -> None:
    p = params(ms_per_char=40)
    fake = ToneTTS(VendorSpec("tts", "elevenlabs", "eleven_flash_v2_5"), p, DelaySampler(PROFILE))
    frames = [ev.frame async for ev in fake.synthesize("Sure, I can help with that.")]
    total = sum(f.duration for f in frames)
    assert abs(total - 27 * 0.040) < 0.05
    assert frame_rms(frames[0]) > 1000


def test_live_registry_swaps_vendors_and_keeps_real_nc() -> None:
    registry = live_registry(params())
    assert isinstance(registry.build(VendorSpec("stt", "deepgram", "nova-3"), {}), EnergySTT)
    nc = registry.build(VendorSpec("nc", "sanas", "vi"), {})
    assert isinstance(nc, rtc.FrameProcessor)


def test_delay_sampler_follows_profile() -> None:
    sampler = DelaySampler({"x": {"median": 200, "p95": 400}}, random.Random(1))
    values = sorted(sampler.seconds("x", 0) for _ in range(2000))
    assert abs(values[1000] - 0.2) < 0.02
    assert abs(values[1900] - 0.4) < 0.06
    assert sampler.seconds("missing", 75) == 0.075


def test_monitor_detects_onsets_after_quiet() -> None:
    monitor = AgentAudioMonitor(threshold=300, min_gap_s=0.15)
    for at, rms in [(1.0, 50), (1.01, 900), (1.02, 900), (1.1, 900), (1.5, 10), (1.6, 800)]:
        monitor.feed(rms, at)
    assert monitor.onsets == [1.01, 1.6]


async def test_fake_internal_api_claims_and_checks_events() -> None:
    fake = FakeInternalApi(load_agent_config())
    url = await fake.start()
    headers = {"Authorization": f"Bearer {SERVICE_TOKEN}"}
    try:
        async with httpx.AsyncClient() as http:
            denied = await http.post(f"{url}/calls/claim", json={})
            assert denied.status_code == 401
            claim = await http.post(
                f"{url}/calls/claim",
                headers=headers,
                json={"dispatch_metadata": {"call_id": "call_x"}, "job_id": "j"},
            )
            body = claim.json()
            assert body["admitted"] and body["call_id"] == "call_x"
            assert body["runtime"]["config"]["stt"]["provider"] == "deepgram"
            events = [
                {"seq": 1, "type": "status", "occurred_at": "t", "status": "in_progress"},
                {"seq": 1, "type": "bogus", "occurred_at": "t"},
                {"seq": 3, "type": "status", "occurred_at": "t", "status": "ended"},
            ]
            ok = await http.post(
                f"{url}/calls/call_x/events", headers=headers, json={"events": events}
            )
            assert ok.status_code == 200
            closed = await http.post(
                f"{url}/calls/call_x/events", headers=headers, json={"events": []}
            )
            assert closed.status_code == 409
    finally:
        await fake.stop()
    assert fake.ended_event("call_x").is_set()
    assert len(fake.violations) == 2  # unknown type and a repeated seq


def test_summarize_pairs_caller_and_worker_turns() -> None:
    events = [
        {"type": "turn", "turn_index": 0, "e2e_ms": 300},
        {"type": "turn", "turn_index": 1, "e2e_ms": 700, "eou_delay_ms": 600, "llm_ttft_ms": 200},
        {"type": "turn", "turn_index": 2, "e2e_ms": 800, "eou_delay_ms": 610, "llm_ttft_ms": None},
    ]
    results = [
        CallResult("a", [900.0, 1000.0], events),
        CallResult("b", [None], [], error=None),
    ]
    report = summarize(results, violations=0, wall_s=3.0, calls=2)
    assert report.turns == 2 and report.missed_turns == 1
    assert report.e2e_p50_ms == 900.0 and report.e2e_p95_ms == 1000.0
    assert report.worker_minus_caller_median_ms == -200.0
    assert report.greeting_median_ms == 300.0 and report.llm_ttft_median_ms == 200.0
    assert report.details[0]["turns"][1]["worker_e2e_ms"] == 800
    assert "details" not in report.to_json()


PAUSES = synth.BENCH_DIR / "callset_pauses.yaml"


def test_pause_fixtures_match_the_generator() -> None:
    """R4 scenarios: each turn is its parts with the call set's pause between them."""
    callset = yaml.safe_load(PAUSES.read_text())
    directory = synth.fixtures_dir(callset)
    assert directory == synth.FIXTURES_DIR / "pauses"
    for i, raw in enumerate(callset["turns"]):
        turn = synth.Turn.parse(raw)
        assert len(turn.segments) >= 2
        committed, rate = synth.read_wav(directory / synth.fixture_name(i))
        expected = synth.to_pcm16(synth.synthesize_turn(turn.say, pause_ms=turn.pause_ms))
        assert committed.shape == expected.shape
        assert int(np.max(np.abs(committed.astype(np.int32) - expected))) <= 2
        # The pause is real silence in the middle of the turn.
        gap = int(turn.pause_ms / 1000 * rate)
        first = synth.to_pcm16(synth.synthesize(turn.segments[0]))
        assert not np.any(committed[len(first) : len(first) + gap])


def test_turn_without_pause_mark_is_unchanged() -> None:
    text = "Please send me the payment link."
    assert synth.segments(text) == [text]
    assert np.array_equal(synth.synthesize_turn(text), synth.synthesize(text))


def test_fake_stt_gets_one_transcript_per_part() -> None:
    callset = {"turns": ["one", {"say": "two a | two b", "pause_ms": 700}]}
    assert scripted_transcripts(callset) == ["one", "two a", "two b"]


def test_summarize_counts_cut_offs() -> None:
    results = [
        CallResult("a", [900.0, 1000.0], cutoffs=[False, True]),
        CallResult("b", [800.0], cutoffs=[False]),
    ]
    report = summarize(results, violations=0, wall_s=1.0, calls=2)
    assert report.cutoffs == 1
    assert [t["cutoff"] for t in report.details[0]["turns"]] == [False, True]
    assert report.to_json()["cutoffs"] == 1
