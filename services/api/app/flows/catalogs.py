"""Node override checks against the 002 catalogs (T078, T114; FR-009, FR-054).

Providers, models, voices and languages must exist in the LLM and voice catalogs
(``E_UNKNOWN_CATALOG``); numeric values are checked with 002's ``validate_override`` against the
shared ``controls`` range table, never a second table here (``E_INVALID_FIELD``).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.agents.offered import llm_offer, stt_offer, tts_offer
from app.agents.validation import validate_override
from app.voices.catalog import load_catalog as load_voice_catalog

Problem = tuple[str, str, str]
TTS_NUMBERS = ("speed", "volume", "expressiveness")


def _section(overrides: Mapping[str, Any], key: str) -> Mapping[str, Any] | None:
    value = overrides.get(key)
    return value if isinstance(value, Mapping) and value else None


def check_overrides(overrides: Mapping[str, Any]) -> list[Problem]:
    out: list[Problem] = []
    voices = load_voice_catalog()

    llm = _section(overrides, "llm")
    if llm is not None:
        provider, model_id = str(llm.get("provider") or ""), str(llm.get("model") or "")
        offer = llm_offer(provider, model_id) if provider and model_id else None
        model = offer.model if offer is not None else None
        if offer is None or model is None or offer.status == "withdrawn":
            out.append(
                ("E_UNKNOWN_CATALOG", "llm.model", "This model is not offered any more. Choose another.")
            )
        temperature = llm.get("temperature")
        if model is not None and temperature is not None:
            rule = model.temperature
            if isinstance(temperature, bool) or not isinstance(temperature, int | float):
                out.append(("E_INVALID_FIELD", "llm.temperature", "Enter a number."))
            elif rule.is_fixed:
                if float(temperature) != rule.fixed:
                    out.append(
                        ("E_INVALID_FIELD", "llm.temperature", f"This model always runs at {rule.fixed}.")
                    )
            elif not (rule.min or 0) <= float(temperature) <= (rule.max or 2):
                out.append(
                    (
                        "E_INVALID_FIELD",
                        "llm.temperature",
                        f"Temperature must be between {rule.min} and {rule.max}.",
                    )
                )

    tts = _section(overrides, "tts")
    if tts is not None:
        tts_model = tts.get("model")
        tts_found = tts_offer(str(tts.get("provider") or ""), str(tts_model) if tts_model else None, voices)
        tts_provider = tts_found.provider
        if tts_provider is None:
            out.append(
                ("E_UNKNOWN_CATALOG", "tts.provider", "This voice provider is not available. Choose another.")
            )
        else:
            if tts_found.status == "unknown_model":
                out.append(("E_UNKNOWN_CATALOG", "tts.model", "This voice model is not offered any more."))
            voice = tts.get("voice_id")
            if not voice:
                out.append(("E_UNKNOWN_CATALOG", "tts.voice_id", "Choose a voice."))
            elif tts_provider.curated and not tts_provider.owns_voice(str(voice)):
                out.append(
                    ("E_UNKNOWN_CATALOG", "tts.voice_id", "This voice is not available. Choose another.")
                )
        for key in TTS_NUMBERS:
            if tts.get(key) is not None:
                for issue in validate_override(f"tts.{key}", tts[key], voices):
                    out.append(("E_INVALID_FIELD", f"tts.{key}", issue["message"]))

    stt = _section(overrides, "stt")
    if stt is not None:
        stt_model = stt.get("model")
        stt_found = stt_offer(str(stt.get("provider") or ""), str(stt_model) if stt_model else None, voices)
        if stt_found.provider is None:
            out.append(
                ("E_UNKNOWN_CATALOG", "stt.provider", "This speech recognition provider is not available.")
            )
        elif stt_found.status == "unknown_model":
            out.append(
                ("E_UNKNOWN_CATALOG", "stt.model", "This speech recognition model is not offered any more.")
            )

    language = overrides.get("language")
    if language and voices.language(str(language)) is None:
        out.append(("E_UNKNOWN_CATALOG", "language", "This language is not supported."))
    return out
