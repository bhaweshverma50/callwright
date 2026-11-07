"""ElevenLabs streaming TTS (default launch voice vendor).

Expressiveness (the editor's 0..2 slider, default 0.9) maps to ElevenLabs voice settings:

=============  =========  =====================================  =========================
expressiveness stability  style (Multilingual v2 only)           meaning
=============  =========  =====================================  =========================
0.0            0.90       0.00                                   steady, read-out delivery
0.9 (default)  0.35       0.30                                   natural, expressive
2.0            0.15       0.60                                   most varied
=============  =========  =====================================  =========================

Both are linear between those points. The default is the "expressive" setting chosen by ear
on Multilingual v2 (stability 0.35, similarity 0.75, style 0.3, speaker boost on). Similarity
stays 0.75 and speaker boost is on for every model. ``style`` is sent only to models that
support style exaggeration (Multilingual v2); Flash and Turbo models ignore it, so it is
left out for them.
"""

from __future__ import annotations

from collections.abc import Mapping
from itertools import pairwise
from typing import Any

from worker.adapters.registry import VendorSpec
from worker.adapters.tts import clamp, opt_float

DEFAULT_EXPRESSIVENESS = 0.9
SIMILARITY = 0.75
STYLE_MODELS = frozenset({"eleven_multilingual_v2"})
# Models that accept a language code (enforced language and text normalisation).
LANGUAGE_CODE_MODELS = frozenset({"eleven_flash_v2_5", "eleven_turbo_v2_5"})

_STABILITY = ((0.0, 0.9), (DEFAULT_EXPRESSIVENESS, 0.35), (2.0, 0.15))
_STYLE = ((0.0, 0.0), (DEFAULT_EXPRESSIVENESS, 0.3), (2.0, 0.6))


def native_volume(model: str | None) -> bool:
    """Whether the vendor applies ``volume`` itself; otherwise the worker applies gain."""
    return False


def _piecewise(points: tuple[tuple[float, float], ...], x: float) -> float:
    x = clamp(x, points[0][0], points[-1][0])
    for (x0, y0), (x1, y1) in pairwise(points):
        if x <= x1:
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return points[-1][1]


def stability_for(expressiveness: float) -> float:
    """Expressiveness 0..2 (higher = more variation) to ElevenLabs stability 0.9..0.15."""
    return round(_piecewise(_STABILITY, expressiveness), 3)


def style_for(expressiveness: float) -> float:
    """Expressiveness 0..2 to ElevenLabs style exaggeration 0..0.6."""
    return round(_piecewise(_STYLE, expressiveness), 3)


def voice_settings(model: str, expressiveness: float, speed: float) -> dict[str, Any]:
    settings: dict[str, Any] = {
        "stability": stability_for(expressiveness),
        "similarity_boost": SIMILARITY,
        "speed": clamp(speed, 0.7, 1.2),
        "use_speaker_boost": True,
    }
    if model in STYLE_MODELS:
        settings["style"] = style_for(expressiveness)
    return settings


def build(spec: VendorSpec, creds: Mapping[str, str]) -> Any:
    from livekit.plugins import elevenlabs

    model = spec.required_model
    settings = voice_settings(
        model,
        opt_float(spec.options, "expressiveness", DEFAULT_EXPRESSIVENESS),
        opt_float(spec.options, "speed", 1.0),
    )
    kwargs: dict[str, Any] = {
        "model": model,
        "voice_settings": elevenlabs.VoiceSettings(**settings),
        "api_key": creds.get("api_key", ""),
    }
    language = str(spec.options.get("language") or "").split("-")[0].lower()
    if model in LANGUAGE_CODE_MODELS and language and language not in ("en", "multi"):
        kwargs["language"] = language
    voice_id = spec.options.get("voice_id")
    if voice_id:
        kwargs["voice_id"] = str(voice_id)
    return elevenlabs.TTS(**kwargs)
