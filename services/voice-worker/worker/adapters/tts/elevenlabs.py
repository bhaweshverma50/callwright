"""ElevenLabs streaming TTS (default launch voice vendor)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from worker.adapters.registry import VendorSpec
from worker.adapters.tts import clamp, opt_float


def native_volume(model: str | None) -> bool:
    """Whether the vendor applies ``volume`` itself; otherwise the worker applies gain."""
    return False


def stability_for(expressiveness: float) -> float:
    """Expressiveness 0..2 (higher = more variation) to ElevenLabs stability 1..0."""
    return round(clamp(1.0 - expressiveness / 2.0, 0.0, 1.0), 3)


def build(spec: VendorSpec, creds: Mapping[str, str]) -> Any:
    from livekit.plugins import elevenlabs

    settings = elevenlabs.VoiceSettings(
        stability=stability_for(opt_float(spec.options, "expressiveness", 0.9)),
        similarity_boost=0.75,
        speed=clamp(opt_float(spec.options, "speed", 1.0), 0.7, 1.2),
    )
    kwargs: dict[str, Any] = {
        "model": spec.model or "eleven_flash_v2_5",
        "voice_settings": settings,
        "api_key": creds.get("api_key", ""),
    }
    voice_id = spec.options.get("voice_id")
    if voice_id:
        kwargs["voice_id"] = str(voice_id)
    return elevenlabs.TTS(**kwargs)
