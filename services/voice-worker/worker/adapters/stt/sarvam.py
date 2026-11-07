"""Sarvam AI STT (Saarika, Saaras) for Indic languages and ``en-IN``."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from worker.adapters.registry import VendorSpec
from worker.adapters.stt import language_base


def sarvam_language(language: str) -> str:
    """Sarvam expects BCP-47 with the India region, for example ``hi-IN``."""
    if language.lower() in {"multi", "hi-latn"}:
        return "unknown" if language.lower() == "multi" else "hi-IN"
    return f"{language_base(language)}-IN"


def build(spec: VendorSpec, creds: Mapping[str, str]) -> Any:
    from livekit.plugins import sarvam

    language = sarvam_language(str(spec.options.get("language", "en-IN")))
    return sarvam.STT(
        language=language, model=spec.required_model, api_key=creds.get("api_key", "")
    )
