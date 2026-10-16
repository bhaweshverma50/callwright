"""Cartesia Sonic streaming TTS."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from worker.adapters.registry import VendorSpec
from worker.adapters.stt import language_base
from worker.adapters.tts import clamp, opt_float

# Speed and volume controls exist only on Sonic 3 (speed 0.6..2.0, volume 0.5..2.0). Other
# models get the worker's output gain for volume and the vendor's natural pace.
CONTROL_MODELS = frozenset({"sonic-3"})


def native_volume(model: str | None) -> bool:
    return (model or "sonic-2") in CONTROL_MODELS


def build(spec: VendorSpec, creds: Mapping[str, str]) -> Any:
    from livekit.plugins import cartesia

    model = spec.model or "sonic-2"
    kwargs: dict[str, Any] = {
        "api_key": creds.get("api_key", ""),
        "model": model,
        "language": language_base(str(spec.options.get("language", "en"))),
    }
    if model in CONTROL_MODELS:
        kwargs["speed"] = clamp(opt_float(spec.options, "speed", 1.0), 0.6, 2.0)
        kwargs["volume"] = clamp(opt_float(spec.options, "volume", 1.0), 0.5, 2.0)
    voice_id = spec.options.get("voice_id")
    if voice_id:
        kwargs["voice"] = str(voice_id)
    return cartesia.TTS(**kwargs)
