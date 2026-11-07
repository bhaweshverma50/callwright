"""Deepgram STT (Nova-3, Nova-2, Flux with built-in end of turn)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from callwright_contract.adapters import load_catalog

from worker.adapters.registry import VendorSpec

# Flux sends an eager end of turn at this confidence, before the final one (0.7 by default);
# the transcript starts the reply early (preemptive generation) and is redone if speech resumes.
FLUX_EAGER_EOT_THRESHOLD = 0.4


def build(spec: VendorSpec, creds: Mapping[str, str]) -> Any:
    from livekit.plugins import deepgram

    model = spec.required_model
    api_key = creds.get("api_key", "")
    entry = load_catalog().entry("stt", "deepgram")
    if entry is not None and model in entry.builtin_turn_detection:
        # Flux runs on Deepgram's v2 listen API and supplies its own end-of-turn signal (R5).
        return deepgram.STTv2(
            model=model, api_key=api_key, eager_eot_threshold=FLUX_EAGER_EOT_THRESHOLD
        )
    language = str(spec.options.get("language", "en-US"))
    return deepgram.STT(model=model, language=language, api_key=api_key)
