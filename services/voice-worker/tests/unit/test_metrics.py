"""Per-turn latency, usage meters and contract-shaped events (research R6, R7)."""

from __future__ import annotations

from datetime import UTC, datetime

from livekit.agents.metrics import EOUMetrics, LLMMetrics, STTMetrics, TTSMetrics

from tests.harness.fakes import contract_errors
from worker.metrics import (
    EventRecorder,
    LatencyTracker,
    MetricsBridge,
    TurnRecord,
    UsageMeters,
    latency_payload,
)


def test_meters_are_cumulative_per_provider_and_model() -> None:
    m = UsageMeters()
    m.add_stt("deepgram", "nova-3", 1000.4)
    m.add_stt("deepgram", "nova-3", 500)
    m.add_stt("deepgram", "nova-2", 250)
    m.add_llm("azure_openai", "gpt-5.1", input_tokens=100, cached_input_tokens=40, output_tokens=7)
    m.add_llm("azure_openai", "gpt-5.1", input_tokens=120, cached_input_tokens=100, output_tokens=9)
    m.add_tts("elevenlabs", "eleven_flash_v2_5", 30)
    m.add_tts("elevenlabs", "eleven_flash_v2_5", -5)  # never decreases
    m.set_nc("none", "none", 1000)  # passthrough is not metered
    snap = m.snapshot()
    assert snap["stt"] == [
        {"provider": "deepgram", "model": "nova-3", "audio_ms": 1500},
        {"provider": "deepgram", "model": "nova-2", "audio_ms": 250},
    ]
    assert snap["llm"] == [
        {
            "provider": "azure_openai",
            "model": "gpt-5.1",
            "input_tokens": 220,
            "cached_input_tokens": 140,
            "output_tokens": 16,
        }
    ]
    assert snap["tts"] == [
        {"provider": "elevenlabs", "model": "eleven_flash_v2_5", "characters": 30}
    ]
    assert snap["nc"] == []


def test_set_meters_never_go_down() -> None:
    m = UsageMeters()
    m.set_nc("sanas", "vi", 5000)
    m.set_nc("sanas", "vi", 4000)
    assert m.snapshot()["nc"][0]["audio_ms"] == 5000


def test_latency_tracker_measures_e2e_directly() -> None:
    t = LatencyTracker()
    t.connected(100.0)
    greeting = t.begin_turn(greeting=True)
    t.component("tts_ttfb", 0.12)
    assert t.agent_audio_started(100.4) is greeting
    assert greeting.turn_index == 0 and greeting.e2e_ms == 400
    assert t.agent_audio_started(100.9) is None  # first audio only

    t.user_speech_ended(105.0)
    turn = t.begin_turn()
    t.component("stt_final", 0.15)
    t.component("eou_delay", 0.41)
    t.component("llm_ttft", 0.3)
    t.component("llm_ttft", 0.9)  # second generation after a tool: first one counts
    t.component("tool", 0.2)
    t.component("tool", 0.1)
    t.component("tts_ttfb", 0.11)
    t.agent_audio_started(105.83)
    assert turn.turn_index == 1
    assert (turn.stt_final_ms, turn.eou_delay_ms, turn.llm_ttft_ms) == (150, 410, 300)
    assert (turn.tool_ms, turn.tts_ttfb_ms, turn.e2e_ms) == (300, 110, 830)
    assert t.begin_turn().turn_index == 2


def test_turn_commit_before_thinking_keeps_components_and_anchor() -> None:
    """Live order (found by the live benchmark): VAD end of speech, then the framework commits
    the turn (EOU metrics, backdated last speaking time), then the agent starts thinking."""
    tracker = LatencyTracker()
    bridge = MetricsBridge(tracker, UsageMeters(), lambda kind: ("p", "m"))
    tracker.connected(100.0)
    greeting = tracker.begin_turn(greeting=True)
    tracker.agent_audio_started(100.5)
    assert greeting.e2e_ms == 500
    # Caller stopped at 110.0; VAD reports it 0.55 s later; commit at 110.62 after a 20 ms hook.
    tracker.user_speech_ended(110.55)
    bridge.on_metrics(
        EOUMetrics(
            timestamp=110.64,
            end_of_utterance_delay=0.62,
            transcription_delay=0.16,
            on_user_turn_completed_delay=0.02,
        )
    )
    assert greeting.stt_final_ms is None  # never written to the finished greeting
    turn = tracker.begin_turn()
    tracker.agent_audio_started(111.0)
    assert (turn.stt_final_ms, turn.eou_delay_ms) == (160, 620)
    assert turn.e2e_ms == 1000  # from 110.0, not from the VAD event at 110.55

    # Commit after thinking started (other order): applied to the open turn directly.
    tracker.user_speech_ended(120.5)
    second = tracker.begin_turn()
    bridge.on_metrics(
        EOUMetrics(
            timestamp=120.6,
            end_of_utterance_delay=0.6,
            transcription_delay=0.2,
            on_user_turn_completed_delay=0.0,
        )
    )
    tracker.agent_audio_started(120.9)
    assert (second.stt_final_ms, second.eou_delay_ms, second.e2e_ms) == (200, 600, 900)

    # Keypad turns have no EOU metrics: the flush time stays the anchor.
    tracker.user_speech_ended(130.0)
    keypad = tracker.begin_turn()
    tracker.agent_audio_started(130.7)
    assert keypad.e2e_ms == 700 and keypad.stt_final_ms is None

    # A trailing LLM generation of a finished reply is not moved to the next turn...
    tracker.component("llm_ttft", 0.9)
    # ...but a preemptive generation after the caller started speaking is.
    tracker.user_speech_started()
    tracker.component("llm_ttft", 0.31)
    tracker.component("llm_ttft", 0.5)  # a preemptive retry: the first one counts
    tracker.component("tts_ttfb", 0.14)  # preemptive TTS (R4) is held the same way
    tracker.user_speech_ended(140.0)
    preemptive = tracker.begin_turn()
    assert (preemptive.llm_ttft_ms, preemptive.tts_ttfb_ms) == (310, 140)


def test_metrics_bridge_maps_framework_metrics() -> None:
    tracker = LatencyTracker()
    meters = UsageMeters()
    models = {"llm": ("azure_openai", "gpt-5.1"), "stt": ("deepgram", "nova-3")}
    bridge = MetricsBridge(tracker, meters, lambda kind: models[kind])
    tracker.user_speech_ended(1.0)
    turn = tracker.begin_turn()
    bridge.on_metrics(
        EOUMetrics(
            timestamp=0,
            end_of_utterance_delay=0.42,
            transcription_delay=0.16,
            on_user_turn_completed_delay=0,
        )
    )
    bridge.on_metrics(
        LLMMetrics(
            label="x",
            request_id="r",
            timestamp=0,
            duration=1,
            ttft=0.31,
            cancelled=False,
            completion_tokens=12,
            prompt_tokens=900,
            prompt_cached_tokens=600,
            total_tokens=912,
            tokens_per_second=10,
        )
    )
    bridge.on_metrics(
        TTSMetrics(
            label="x",
            request_id="r",
            timestamp=0,
            ttfb=0.13,
            duration=1,
            audio_duration=2,
            cancelled=False,
            characters_count=40,
            streamed=True,
        )
    )
    bridge.on_metrics(
        STTMetrics(
            label="x", request_id="r", timestamp=0, duration=0, audio_duration=5.5, streamed=True
        )
    )
    assert (turn.stt_final_ms, turn.eou_delay_ms) == (160, 420)
    assert (turn.llm_ttft_ms, turn.tts_ttfb_ms) == (310, 130)
    snap = meters.snapshot()
    assert snap["llm"][0]["input_tokens"] == 900
    assert snap["llm"][0]["cached_input_tokens"] == 600
    assert snap["stt"] == [{"provider": "deepgram", "model": "nova-3", "audio_ms": 5500}]
    assert snap["tts"] == []  # characters come from the TTS node, after pronunciation


def test_recorder_events_follow_the_contract() -> None:
    clock = [0.0]
    rec = EventRecorder(
        wall_clock=lambda: datetime(2026, 10, 16, tzinfo=UTC), monotonic=lambda: clock[0]
    )
    assert rec.status("in_progress")["offset_ms"] is None  # before connection
    rec.connected()
    clock[0] = 1.5
    tracker = LatencyTracker()
    turn = tracker.begin_turn(greeting=True)
    turn.e2e_ms = 300
    events = [
        rec.turn(turn),
        rec.message("agent", "Hello", started_ms=0, ended_ms=900, turn_index=0, interrupted=False),
        rec.message("user", "1234", started_ms=1, ended_ms=2, source="keypad"),
        rec.system("silence_timeout"),
        rec.usage(),
        rec.tool_call("lookup", arguments={"a": 1}, output="x" * 9000, duration_ms=5),
        rec.flow_transition("n_2", "n_1", "next"),
        rec.dtmf("12#", "received", "termination_key"),
        rec.warning("vendor_retry", component="tts", provider="elevenlabs", detail="slow"),
        rec.warning("vendor_error", component="stt", level="error"),
        rec.status("ended", disconnect_reason="user_hangup"),
    ]
    assert [e["seq"] for e in events] == list(range(2, 13)) and rec.pending == 12
    assert events[0]["offset_ms"] == 1500
    assert len(events[5]["output"]) == 8192
    for event in events:
        assert contract_errors(event) == [], event
    batch = rec.drain(5)
    assert len(batch) == 5 and rec.pending == 7
    rec.requeue(batch)
    assert rec.drain()[0]["seq"] == 1


def test_latency_payload_splits_the_measured_answer_time() -> None:
    turn = TurnRecord(turn_index=2, llm_ttft_ms=300, tool_ms=50, tts_ttfb_ms=120, e2e_ms=900)
    assert latency_payload(turn) == {
        "turn_index": 2,
        "stt_ms": 430,
        "llm_ms": 350,
        "tts_ms": 120,
        "e2e_ms": 900,
    }


def test_latency_payload_scales_preemptive_parts_into_the_answer_time() -> None:
    # The model started before the caller finished: model plus voice exceed the answer time.
    turn = TurnRecord(turn_index=1, llm_ttft_ms=600, tts_ttfb_ms=200, e2e_ms=400)
    payload = latency_payload(turn)
    assert payload is not None
    assert payload["stt_ms"] + payload["llm_ms"] + payload["tts_ms"] == 400
    assert (payload["stt_ms"], payload["llm_ms"], payload["tts_ms"]) == (0, 300, 100)


def test_latency_payload_without_e2e_uses_components_and_skips_empty_turns() -> None:
    turn = TurnRecord(turn_index=1, stt_final_ms=80, eou_delay_ms=200, llm_ttft_ms=310)
    assert latency_payload(turn) == {"turn_index": 1, "stt_ms": 280, "llm_ms": 310, "tts_ms": 0}
    assert latency_payload(TurnRecord(turn_index=3)) is None
    assert latency_payload(TurnRecord(turn_index=0, e2e_ms=700)) is None
