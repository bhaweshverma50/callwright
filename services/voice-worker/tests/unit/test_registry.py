"""T061: every catalog entry builds through the registry with fake credentials."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from callwright_contract.adapters import load_catalog
from callwright_contract.protocol import SttAuto

from tests.harness.runner import claim_tables
from worker.adapters.registry import (
    AdapterRegistry,
    UnsupportedLanguage,
    UnsupportedVendor,
    VendorSpec,
    has_module,
)
from worker.pipeline import auto_stt
from worker.settings import WorkerSettings

REPO = Path(__file__).resolve().parents[4]
PROVIDERS_JSON = REPO / "research" / "live" / "config-providers.json"

FAKE_CREDS = {"api_key": "test-key", "endpoint": "https://example.openai.azure.com"}
OPTIONS = {"language": "en-US", "voice_id": "v1", "speed": 1.0, "expressiveness": 0.9}

CASES = [(e.kind, e.provider, m) for e in load_catalog().entries for m in e.models]


@pytest.mark.parametrize(("kind", "provider", "model"), CASES, ids=["/".join(c) for c in CASES])
async def test_every_catalog_entry_builds(kind: str, provider: str, model: str) -> None:
    registry = AdapterRegistry()
    built = registry.build(VendorSpec(kind, provider, model, OPTIONS), FAKE_CREDS)  # type: ignore[arg-type]
    if provider == "none":
        assert built is None
    else:
        assert built is not None


def test_every_catalog_entry_has_a_module() -> None:
    for entry in load_catalog().entries:
        assert has_module(entry.kind, entry.provider), entry


def test_unknown_provider_and_model_raise() -> None:
    registry = AdapterRegistry()
    with pytest.raises(UnsupportedVendor) as exc:
        registry.check(VendorSpec("tts", "acme", "x"))
    assert exc.value.diagnostic == "unsupported_vendor:tts/acme"
    with pytest.raises(UnsupportedVendor):
        registry.check(VendorSpec("stt", "deepgram", "nova-9"))
    with pytest.raises(UnsupportedVendor):
        registry.build(VendorSpec("llm", "mistral", "large"), {})


def test_azure_alias_normalises() -> None:
    spec = AdapterRegistry().check(VendorSpec("llm", "azure", "gpt-5.1"))
    assert spec.provider == "azure_openai"


@pytest.mark.parametrize(
    ("provider", "language", "model"),
    [
        ("deepgram", "en-US", "nova-3"),
        ("deepgram", "en-IN", "nova-3"),
        ("deepgram", "hi", "nova-2"),
        ("deepgram", "multi", "nova-3"),
        ("assemblyai", "en-GB", "universal-streaming"),
        ("assemblyai", "es", "universal-streaming-multilingual"),
        ("assemblyai", "pt-BR", "universal-streaming-multilingual"),
        ("sarvam", "hi", "saarika:v2.5"),
        ("sarvam", "ta", "saarika:v2.5"),
    ],
)
def test_auto_stt_follows_the_claim_rules(provider: str, language: str, model: str) -> None:
    """The worker picks what admission picked: the API's rules from the claim (FR-045)."""
    rules = {k: SttAuto.model_validate(v) for k, v in claim_tables()["stt_auto_rules"].items()}
    assert auto_stt(rules, provider, language) == model


def test_auto_stt_uncovered_language_raises() -> None:
    rules = {k: SttAuto.model_validate(v) for k, v in claim_tables()["stt_auto_rules"].items()}
    with pytest.raises(UnsupportedLanguage):
        auto_stt(rules, "assemblyai", "hi")
    with pytest.raises(UnsupportedLanguage):
        auto_stt(rules, "acme", "en")


def test_builtin_turn_detection_flags() -> None:
    registry = AdapterRegistry()
    assert registry.builtin_turn_detection(VendorSpec("stt", "deepgram", "flux-general-en"))
    assert registry.builtin_turn_detection(VendorSpec("stt", "assemblyai", "universal-streaming"))
    assert not registry.builtin_turn_detection(VendorSpec("stt", "deepgram", "nova-3"))
    assert not registry.builtin_turn_detection(VendorSpec("stt", "sarvam", "saarika:v2.5"))


def test_catalog_matches_live_provider_ids() -> None:
    """Model ids are the exact ids from the reference walkthrough (002 data-model 8)."""
    live = json.loads(PROVIDERS_JSON.read_text())
    registry = AdapterRegistry()
    for row in live["tts"]:
        assert set(registry.entry("tts", row["id"]).models) == {m["id"] for m in row["models"]}
    for row in live["stt"]:
        ids = {m["id"] for m in row["models"] if m["id"]}
        assert set(registry.entry("stt", row["id"]).models) == ids
    llm_ids = {m["id"] for m in live["llm"]}
    for provider in ("openai", "azure_openai"):
        assert set(registry.entry("llm", provider).models) == llm_ids


def test_settings_have_credentials_for_every_provider() -> None:
    creds = WorkerSettings().vendor_credentials()
    for entry in load_catalog().entries:
        assert entry.provider in creds
