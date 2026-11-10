from __future__ import annotations

import json
from dataclasses import fields
from importlib import resources

import pytest
from pydantic import ValidationError

from callwright_contract.adapters import AdapterEntry, load_catalog
from callwright_contract.diagnostics import (
    CALLER_NEVER_JOINED,
    FLOW_NOT_COMPILED,
    FLOW_RUNTIME_UNAVAILABLE,
    OUTBOUND_DIAL_MISSING,
    STT_LANGUAGE_UNSUPPORTED,
    UNSUPPORTED_VENDOR,
    VENDOR_ERROR,
    Diagnostic,
    diagnostic,
    parse,
)
from callwright_contract.protocol import SttAuto, TranscriptItem

RULE = SttAuto(
    default="general",
    by_language={"en": "english", "es": "multi"},
    languages={"english": ["en", "en-US"], "general": ["de", "fr"], "multi": ["es"]},
)


def test_stt_auto_picks_exact_then_base_then_default() -> None:
    assert RULE.resolve("en-US") == "english"
    assert RULE.resolve("es") == "multi"
    assert RULE.resolve("de") == "general"


def test_stt_auto_needs_a_model_that_lists_the_language() -> None:
    assert RULE.pick("en-GB") == "english"
    assert RULE.resolve("en-GB") is None
    assert RULE.resolve("ja") is None


def test_adapter_catalog_lookups() -> None:
    catalog = load_catalog()
    assert catalog.canonical_provider("llm", "azure") == "azure_openai"
    assert catalog.supports("tts", "elevenlabs", "eleven_flash_v2_5")
    assert not catalog.supports("tts", "elevenlabs", "nope")
    assert not catalog.supports("tts", "acme", None)
    assert all(e.default_model in e.models for e in catalog.entries if e.kind == "tts")


def test_system_items_name_a_known_event() -> None:
    assert TranscriptItem(type="system", event="vendor_error").event == "vendor_error"
    with pytest.raises(ValidationError):
        TranscriptItem(type="system", event="something_else")


def test_diagnostics_format_and_parse() -> None:
    text = diagnostic(VENDOR_ERROR, "tts", "cartesia")
    assert text == "vendor_error:tts/cartesia"
    assert parse(text) == Diagnostic(VENDOR_ERROR, ("tts", "cartesia"))
    assert diagnostic(UNSUPPORTED_VENDOR, "stt", "acme", None) == "unsupported_vendor:stt/acme"
    assert parse(CALLER_NEVER_JOINED) == Diagnostic(CALLER_NEVER_JOINED)
    codes = [STT_LANGUAGE_UNSUPPORTED, FLOW_NOT_COMPILED, FLOW_RUNTIME_UNAVAILABLE, OUTBOUND_DIAL_MISSING]
    assert all(c.replace("_", "").isalpha() and c.islower() for c in codes)


def test_every_adapter_catalog_key_is_read() -> None:
    raw = json.loads(resources.files("callwright_contract").joinpath("adapters.json").read_text())
    assert set(raw) == {"description", "entries", "ambience_clips"}
    known = {f.name for f in fields(AdapterEntry)}
    assert all(set(entry) <= known for entry in raw["entries"])
    catalog = load_catalog()
    for entry in catalog.entries:
        capable = entry.builtin_turn_detection | entry.native_volume | entry.fixed_temperature
        assert capable <= set(entry.models), entry.provider
    assert catalog.ambience_clips["hold_music"] == "HOLD_MUSIC"
