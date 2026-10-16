"""AssemblyAI streaming STT (built-in end of turn on both launch models)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from worker.adapters.registry import VendorSpec

# Catalog ids (002) to the plugin's model names.
PLUGIN_MODELS = {
    "universal-streaming": "universal-streaming-english",
    "universal-streaming-multilingual": "universal-streaming-multilingual",
}


def build(spec: VendorSpec, creds: Mapping[str, str]) -> Any:
    from livekit.plugins import assemblyai

    model = PLUGIN_MODELS[spec.model or "universal-streaming"]
    kwargs: dict[str, Any] = {"model": model, "api_key": creds.get("api_key", "")}
    if model == "universal-streaming-multilingual":
        # Language steering (``language_codes``) is limited to the Universal-3 Pro family in the
        # plugin; the multilingual streaming model detects es, fr, de, it and pt itself.
        kwargs["language_detection"] = True
    return assemblyai.STT(**kwargs)
