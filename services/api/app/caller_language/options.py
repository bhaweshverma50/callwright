"""Which languages a caller can switch an agent to (012). Pure: reads only the speech catalog.

A language is offered when the agent's speech recognition provider has a model for it and its
voice speaks it:

* speech recognition: the agent's model when it covers the language, else what Auto picks for
  the language (``voices.resolve_auto_stt``), else the provider's first model that covers it.
  The provider never changes, so the agent's vendor keys and pricing rows stay the same;
* voice: the agent's model when it speaks the language, else that model's
  ``multilingual_model`` (English-only Flash v2 and Turbo v2 switch to their v2.5 versions,
  same price), else the language is not offered.

``advanced.language_switching.languages`` limits the offer; empty means one code per base
language (the bare code when supported, so ``hi`` rather than ``hi-Latn``). The agent's own
language comes first and other variants of it are never offered. Flow agents and agents with
the setting off get no options, and neither does an agent with nothing to switch to.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.voices.catalog import VoiceCatalog
from app.voices.catalog import load_catalog as load_voice_catalog

DEFAULT_LANGUAGE = "en-US"
DEFAULT_STT_PROVIDER = "deepgram"
DEFAULT_TTS_PROVIDER = "elevenlabs"
MAX_LANGUAGES = 30


def _section(config: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = config.get(key)
    return value if isinstance(value, Mapping) else {}


def base(code: str) -> str:
    return code.split("-", 1)[0].lower()


def switching(config: Mapping[str, Any]) -> tuple[bool, list[str]]:
    """``(enabled, languages)`` with the defaults for configs written before 012."""
    raw = _section(_section(config, "advanced"), "language_switching")
    enabled = raw.get("enabled", True) is not False
    languages = [str(c) for c in raw.get("languages") or [] if isinstance(c, str)]
    return enabled, languages


def stt_model_for(provider: str, model: str | None, language: str, vc: VoiceCatalog) -> str | None:
    speech = vc.stt_provider(provider)
    if speech is None:
        return None
    if model and speech.covers(model, language):
        return model
    auto = vc.resolve_auto_stt(provider, language)
    if auto and speech.covers(auto, language):
        return auto
    found = speech.models_for_language(language)
    return found[0].id if found else None


def tts_model_for(provider: str, model: str | None, language: str, vc: VoiceCatalog) -> str | None:
    voice = vc.tts_provider(provider)
    return voice.model_for_language(model, language) if voice is not None else None


def option_for(config: Mapping[str, Any], code: str, vc: VoiceCatalog) -> dict[str, Any] | None:
    """The option for ``code`` (label, speech recognition and voice models), or None when the
    agent's speech recognition or voice cannot handle it."""
    lang = vc.language(code)
    if lang is None or code == "multi":
        return None
    stt = _section(config, "stt")
    tts = _section(config, "tts")
    stt_model = stt_model_for(
        str(stt.get("provider") or DEFAULT_STT_PROVIDER), stt.get("model") or None, code, vc
    )
    tts_model = tts_model_for(
        str(tts.get("provider") or DEFAULT_TTS_PROVIDER), tts.get("model") or None, code, vc
    )
    if stt_model is None or tts_model is None:
        return None
    return {"code": code, "label": lang.label, "stt_model": stt_model, "tts_model": tts_model}


def supported_codes(config: Mapping[str, Any], vc: VoiceCatalog | None = None) -> set[str]:
    """Every catalog code the agent could switch to (used by validation and the editor)."""
    vc = vc or load_voice_catalog()
    return {lang.code for lang in vc.languages if option_for(config, lang.code, vc) is not None}


def language_options(config: Mapping[str, Any], vc: VoiceCatalog | None = None) -> list[dict[str, Any]]:
    """``RuntimeConfig.language_options`` for an agent version's config (agent language first)."""
    vc = vc or load_voice_catalog()
    # Flow agents too: every conversational node gets set_language (the agent-level speech
    # recognition and voice decide what is offered).
    enabled, chosen = switching(config)
    if not enabled:
        return []
    agent_code = str(config.get("language") or DEFAULT_LANGUAGE)
    own = vc.language(agent_code)
    stt = _section(config, "stt")
    tts = _section(config, "tts")
    stt_provider: str = str(stt.get("provider") or DEFAULT_STT_PROVIDER)
    voice = vc.tts_provider(str(tts.get("provider") or DEFAULT_TTS_PROVIDER))
    first = {
        "code": agent_code,
        "label": own.label if own is not None else agent_code,
        # The agent's own models: switching back restores them.
        "stt_model": stt.get("model") or vc.resolve_auto_stt(stt_provider, agent_code),
        "tts_model": tts.get("model") or (voice.default_model if voice is not None else None),
    }
    taken = {base(agent_code)} if agent_code != "multi" else set()
    out: list[dict[str, Any]] = []
    if chosen:
        candidates = chosen
    else:
        by_base: dict[str, list[str]] = {}
        for lang in vc.languages:
            if lang.code != "multi":
                by_base.setdefault(base(lang.code), []).append(lang.code)
        candidates = []
        for key, codes in by_base.items():
            ordered = sorted(codes, key=lambda c: (c != key, codes.index(c)))
            supported = next((c for c in ordered if option_for(config, c, vc) is not None), None)
            if supported is not None:
                candidates.append(supported)
    for code in candidates:
        if code == agent_code or base(code) in taken:
            continue
        option = option_for(config, code, vc)
        if option is None:
            continue
        taken.add(base(code))
        out.append(option)
        if len(out) >= MAX_LANGUAGES:
            break
    return [first, *out] if out else []
