"""Platform defaults for a blank agent (T012, spec Assumptions, research R23): the one defaults
table; ``schemas.py`` field defaults and ``upcast`` read it.

Speech and voice defaults depend on the language and come from ``voices/catalog.yaml``; the model
default comes from ``llms/catalog.yaml``. Every numeric default lies on its control step
(checked by tests/unit/catalog/test_catalog_consistency.py), so editor labels always equal the
stored value.
"""

from __future__ import annotations

import copy
from typing import Any

from app.llms.service import load_catalog as load_llm_catalog
from app.voices.catalog import DEFAULT_LANGUAGE
from app.voices.catalog import load_catalog as load_voice_catalog

CURRENT_SCHEMA_VERSION = 1
DEFAULT_GREETING = "Hi, thanks for calling. How can I help you today?"

TTS_TUNING_DEFAULTS: dict[str, float] = {"speed": 1.0, "expressiveness": 0.9, "volume": 1.0}

CALL_BEHAVIOR_DEFAULTS: dict[str, Any] = {
    "end_on_silence_s": 30,
    "max_duration_s": 600,
    "ring_duration_ms": 5000,
    "interruption_sensitivity": 0.9,
    "responsiveness": 0.8,
}

ADVANCED_DEFAULTS: dict[str, Any] = {
    "webhook_url": None,
    "webhook_timeout_ms": 3000,
    "voicemail_detection": {"enabled": False, "action": "hang_up", "message": None},
    "dtmf": {"enabled": False, "timeout_ms": 2500, "termination_key": "#", "digits": 10},
    "background_audio": {"enabled": False, "source": None, "volume": 0.8},
    "analysis_model": None,
    "pronunciation": [],
    "recording": "inherit",
    "language_switching": {"enabled": True, "languages": []},
}


def llm_defaults() -> dict[str, Any]:
    catalog = load_llm_catalog()
    model = catalog.model(catalog.default_provider, catalog.default_model)
    assert model is not None, "llms/catalog.yaml default model is not offered by the default provider"
    return {
        "provider": catalog.default_provider,
        "model": catalog.default_model,
        "temperature": model.temperature.default_value,
    }


def nc_default() -> dict[str, str] | None:
    option = load_voice_catalog().default_nc()
    return {"provider": option.provider, "model": option.model} if option is not None else None


def tts_defaults(language: str, provider: str | None = None) -> dict[str, Any]:
    base = load_voice_catalog().tts_default_for(language, provider)
    return {**base, **TTS_TUNING_DEFAULTS}


def stt_defaults(language: str) -> dict[str, Any]:
    return load_voice_catalog().stt_default_for(language)


def default_config(agent_type: str = "single_prompt", language: str = DEFAULT_LANGUAGE) -> dict[str, Any]:
    """A fully defaulted AgentConfig v1 (``GET /v1/agents/defaults``)."""
    return {
        "schema_version": CURRENT_SCHEMA_VERSION,
        "type": agent_type,
        "language": language,
        "llm": llm_defaults(),
        "prompt": "",
        "begin_message": DEFAULT_GREETING,
        "start_speaker": "agent",
        "dynamic_variables": [],
        "stt": stt_defaults(language),
        "tts": tts_defaults(language),
        "noise_cancellation": nc_default(),
        "call_behavior": copy.deepcopy(CALL_BEHAVIOR_DEFAULTS),
        "advanced": copy.deepcopy(ADVANCED_DEFAULTS),
        "tool_ids": [],
        "kb_ids": [],
        "flow": None,
        "evals": None,
    }
