"""ElevenLabs voice settings: the expressiveness mapping (default = the expressive setting chosen
by ear: stability 0.35, style 0.3, speaker boost), style only on Multilingual v2, and the default
model for new agents."""

from __future__ import annotations

import itertools

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


def test_build_passes_settings_and_language_code_only_where_supported() -> None:
    built = elevenlabs.build(
        VendorSpec(
            "tts", "elevenlabs", "eleven_multilingual_v2", {"voice_id": "v1", "expressiveness": 0.9}
        ),
        {"api_key": "k"},
    )
    assert built.model == "eleven_multilingual_v2"
    opts = built._opts
    assert opts.voice_settings.style == 0.3 and opts.voice_settings.stability == 0.35
    hindi = elevenlabs.build(
        VendorSpec("tts", "elevenlabs", "eleven_flash_v2_5", {"language": "hi"}), {"api_key": "k"}
    )
    assert hindi._opts.language == "hi"


def test_multilingual_v2_is_the_default_model() -> None:
    assert AdapterRegistry().entry("tts", "elevenlabs").default_model == "eleven_multilingual_v2"
