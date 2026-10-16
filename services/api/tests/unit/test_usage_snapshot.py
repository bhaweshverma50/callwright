"""Money test (003 T025, R7): cumulative usage snapshots are stored by ``seq``; a lower ``seq`` is
ignored and duplicates are harmless."""

from __future__ import annotations

from typing import Any

from pydantic import TypeAdapter

from app.call_events.schemas import CallEventIn
from app.call_events.service import latest_usage
from app.calls.components import usage_meters

ADAPTER: TypeAdapter[Any] = TypeAdapter(CallEventIn)


def usage(seq: int, audio_ms: int, tokens: int) -> Any:
    return ADAPTER.validate_python(
        {
            "seq": seq,
            "type": "usage",
            "occurred_at": "2026-10-16T10:00:00Z",
            "usage": {
                "stt": [{"provider": "deepgram", "model": "nova-3", "audio_ms": audio_ms}],
                "llm": [
                    {"provider": "openai", "model": "gpt-5.1", "input_tokens": tokens, "output_tokens": 5}
                ],
            },
        }
    )


def test_highest_seq_wins_within_a_batch() -> None:
    seq, snap = latest_usage(0, [usage(3, 3000, 30), usage(5, 5000, 50), usage(4, 4000, 40)]) or (0, {})
    assert seq == 5
    assert snap["stt"][0]["audio_ms"] == 5000


def test_lower_or_equal_seq_than_stored_is_ignored() -> None:
    assert latest_usage(5, [usage(5, 1, 1), usage(4, 2, 2)]) is None
    assert latest_usage(5, [usage(6, 9000, 90)]) == (6, latest_usage(0, [usage(6, 9000, 90)])[1])  # type: ignore[index]


def test_replaying_the_same_batch_is_harmless() -> None:
    batch = [usage(7, 7000, 70)]
    stored_seq, stored = latest_usage(0, batch) or (0, {})
    assert latest_usage(stored_seq, batch) is None
    assert stored["llm"][0]["input_tokens"] == 70


def test_meters_sum_every_model_of_a_component() -> None:
    snapshot = {
        "llm": [
            {"provider": "openai", "model": "gpt-5.1", "input_tokens": 100, "output_tokens": 10},
            {"provider": "openai", "model": "gpt-5-mini", "input_tokens": 50, "output_tokens": 5},
        ],
        "tts": [{"provider": "elevenlabs", "model": None, "characters": 300}],
    }
    assert usage_meters(snapshot) == {"llm_input_tokens": 150, "llm_output_tokens": 15, "tts_chars": 300}
    assert usage_meters(None) == {"llm_input_tokens": 0, "llm_output_tokens": 0, "tts_chars": 0}
