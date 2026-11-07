"""Fish Audio streaming TTS. Characters are metered by the worker like every TTS vendor."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from worker.adapters.registry import VendorSpec
from worker.adapters.tts import clamp, opt_float


def temperature_for(expressiveness: float) -> float:
    """Expressiveness 0..2 to Fish Audio sampling temperature 0.1..1.0."""
    return round(clamp(0.2 + 0.4 * expressiveness, 0.1, 1.0), 3)


def build(spec: VendorSpec, creds: Mapping[str, str]) -> Any:
    from livekit.plugins import fishaudio

    kwargs: dict[str, Any] = {
        "api_key": creds.get("api_key", ""),
        "model": spec.required_model,
        "speed": opt_float(spec.options, "speed", 1.0),
        "volume": opt_float(spec.options, "volume", 1.0),
        "temperature": temperature_for(opt_float(spec.options, "expressiveness", 0.9)),
        "latency_mode": "balanced",
    }
    voice_id = spec.options.get("voice_id")
    if voice_id:
        kwargs["voice_id"] = str(voice_id)
    return fishaudio.TTS(**kwargs)
