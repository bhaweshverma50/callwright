from __future__ import annotations

from callwright_contract.adapters import load_catalog
from callwright_contract.protocol import SttAuto

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
