"""ai-coustics noise removal (model ``standard``) through the vendor's LiveKit plugin."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from worker.adapters.registry import VendorSpec

# Catalog model id to the plugin's enhancer model.
ENHANCER_MODELS = {"standard": "QUAIL_L"}


def build(spec: VendorSpec, creds: Mapping[str, str]) -> Any:
    from livekit.plugins import ai_coustics

    model = getattr(ai_coustics.EnhancerModel, ENHANCER_MODELS[spec.required_model])
    kwargs: dict[str, Any] = {"model": model}
    license_key = creds.get("api_key")
    if license_key:
        kwargs["auth"] = ai_coustics.AiCousticsApi(license_key=license_key)
    return ai_coustics.audio_enhancement(**kwargs)
