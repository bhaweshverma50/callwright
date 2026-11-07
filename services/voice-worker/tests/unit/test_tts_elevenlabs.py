"""ElevenLabs voice settings: the expressiveness mapping (default = the expressive setting chosen
by ear: stability 0.35, style 0.3, speaker boost), style only on Multilingual v2, and the default
model for new agents."""

from __future__ import annotations

import itertools
from typing import Any

import pytest

from worker.adapters.registry import AdapterRegistry, VendorSpec
from worker.adapters.tts import elevenlabs


def test_default_expressiveness_is_the_expressive_setting() -> None:
    settings = elevenlabs.voice_settings("eleven_multilingual_v2", 0.9, 1.0)
    assert settings == {
        "stability": 0.35,
        "similarity_boost": 0.75,
        "speed": 1.0,
        "use_speaker_boost": True,
        "style": 0.3,
    }


def test_slider_stays_meaningful_across_its_range() -> None:
    stability = [elevenlabs.stability_for(x / 10) for x in range(21)]
    style = [elevenlabs.style_for(x / 10) for x in range(21)]
    assert stability[0] == 0.9 and stability[-1] == 0.15
    assert style[0] == 0.0 and style[-1] == 0.6
    assert all(a > b for a, b in itertools.pairwise(stability))
    assert all(a < b for a, b in itertools.pairwise(style))
    assert elevenlabs.stability_for(-1) == 0.9 and elevenlabs.style_for(5) == 0.6


def test_style_only_for_models_that_support_it() -> None:
    flash = elevenlabs.voice_settings("eleven_flash_v2_5", 0.9, 1.4)
    assert "style" not in flash and flash["stability"] == 0.35 and flash["speed"] == 1.2
    assert flash["use_speaker_boost"] is True


def test_build_passes_settings_and_language_code_only_where_supported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from livekit.plugins import elevenlabs as plugin

    built: list[dict[str, Any]] = []
    monkeypatch.setattr(plugin, "TTS", lambda **kwargs: built.append(kwargs))
    elevenlabs.build(
        VendorSpec(
            "tts", "elevenlabs", "eleven_multilingual_v2", {"voice_id": "v1", "expressiveness": 0.9}
        ),
        {"api_key": "k"},
    )
    elevenlabs.build(
        VendorSpec("tts", "elevenlabs", "eleven_flash_v2_5", {"language": "hi"}), {"api_key": "k"}
    )
    elevenlabs.build(
        VendorSpec("tts", "elevenlabs", "eleven_flash_v2_5", {"language": "en-US"}),
        {"api_key": "k"},
    )
    multilingual, hindi, english = built
    assert multilingual["model"] == "eleven_multilingual_v2" and multilingual["voice_id"] == "v1"
    settings = multilingual["voice_settings"]
    assert settings.style == 0.3 and settings.stability == 0.35
    assert hindi["language"] == "hi" and "language" not in english


def test_multilingual_v2_is_the_default_model() -> None:
    assert AdapterRegistry().entry("tts", "elevenlabs").default_model == "eleven_multilingual_v2"
