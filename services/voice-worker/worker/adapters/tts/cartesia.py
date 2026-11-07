"""Cartesia Sonic streaming TTS."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from worker.adapters.registry import VendorSpec
from worker.adapters.stt import language_base
from worker.adapters.tts import clamp, opt_float


def build(spec: VendorSpec, creds: Mapping[str, str]) -> Any:
    from livekit.plugins import cartesia

    model = spec.required_model
    kwargs: dict[str, Any] = {
        "api_key": creds.get("api_key", ""),
        "model": model,
        "language": language_base(str(spec.options.get("language", "en"))),
    }
    if spec.entry is not None and model in spec.entry.native_volume:
        # Cartesia's speed and volume controls come together (the catalog's native_volume
        # models: speed 0.6..2.0, volume 0.5..2.0). Other models get the worker's output gain
        # for volume and the vendor's natural pace.
        kwargs["speed"] = clamp(opt_float(spec.options, "speed", 1.0), 0.6, 2.0)
        kwargs["volume"] = clamp(opt_float(spec.options, "volume", 1.0), 0.5, 2.0)
    voice_id = spec.options.get("voice_id")
    if voice_id:
        kwargs["voice"] = str(voice_id)
    return cartesia.TTS(**kwargs)
