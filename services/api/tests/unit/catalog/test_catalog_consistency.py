"""Catalog consistency (T090; FR-039, FR-042, FR-047, FR-048). Runs in CI without a database.

Every option offered in a picker has an exact rate in 001's launch pricing seed under the same id;
one model id across providers; unique language codes and labels in the required order; every
shipped language covered by speech recognition and a voice; every STT provider has Auto or a
default model; every numeric default lies inside its control range and on its step.
"""

from __future__ import annotations

import importlib.util
from decimal import Decimal
from pathlib import Path
from typing import Any

from app.agents import defaults
from app.agents.validation import validate_pure
from app.llms.service import load_catalog as llm_catalog
from app.voices.catalog import load_catalog as voice_catalog

VERSIONS = Path(__file__).resolve().parents[3] / "app/migrations/versions"
# The launch seed and the rows later migrations add to the catalog in effect (003 T069).
PRICING_MIGRATIONS = (
    ("s001_0004_pricing_catalog.py", "SEED_V1"),
    ("s003_0004_anthropic_llm_rates.py", "ROWS"),
)


def seed_keys() -> set[tuple[str, str, str | None]]:
    keys: set[tuple[str, str, str | None]] = set()
    for filename, attr in PRICING_MIGRATIONS:
        spec = importlib.util.spec_from_file_location(filename.removesuffix(".py"), VERSIONS / filename)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        keys |= {(row[0], row[1], row[2]) for row in getattr(module, attr)}
    return keys


SEED = seed_keys()


def test_every_llm_option_priced_exactly() -> None:
    for model in llm_catalog().models:
        for provider in model.providers:
            assert ("llm", provider, model.id) in SEED, (provider, model.id)


def test_one_model_id_across_providers() -> None:
    ids = [m.id for m in llm_catalog().models]
    assert len(ids) == len(set(ids))
    assert all(len(m.providers) == len(set(m.providers)) for m in llm_catalog().models)


def test_every_stt_option_priced_exactly() -> None:
    for provider in voice_catalog().stt:
        assert provider.supports_auto or provider.default_model, provider.provider
        if provider.supports_auto:
            assert ("stt", provider.provider, None) in SEED, provider.provider
            assert provider.auto_default and provider.model(provider.auto_default), provider.provider
            for target in provider.auto_by_language.values():
                assert provider.model(target) is not None
        for model in provider.models:
            assert ("stt", provider.provider, model.id) in SEED, (provider.provider, model.id)


def test_every_tts_and_nc_option_priced_exactly() -> None:
    cat = voice_catalog()
    for provider in cat.tts:
        assert provider.model(provider.default_model) is not None
        for model in provider.models:
            assert ("tts", provider.provider, model.id) in SEED, (provider.provider, model.id)
        assert provider.owns_voice(provider.default_voice)
        for voice in provider.default_voice_by_language.values():
            assert provider.owns_voice(voice), (provider.provider, voice)
    for option in cat.noise_cancellation:
        assert ("nc", option.provider, option.model) in SEED
    assert sum(1 for o in cat.noise_cancellation if o.default) == 1


def test_languages_unique_and_ordered() -> None:
    langs = voice_catalog().languages
    codes = [lang.code for lang in langs]
    labels = [lang.label for lang in langs]
    assert len(codes) == len(set(codes)) == 46
    assert len(labels) == len(set(labels))
    assert codes[0] == "multi" and labels[0] == "Multilingual"
    assert labels[1:] == sorted(labels[1:])


def test_every_language_covered() -> None:
    cat = voice_catalog()
    for lang in cat.languages:
        stt = cat.stt_default_for(lang.code)
        provider = cat.stt_provider(stt["provider"])
        assert provider is not None and provider.covers(stt["model"], lang.code), lang.code
        tts = cat.tts_default_for(lang.code)
        tts_provider = cat.tts_provider(tts["provider"])
        assert tts_provider is not None and tts_provider.owns_voice(tts["voice_id"]), lang.code


def test_every_language_default_config_validates() -> None:
    for lang in voice_catalog().languages:
        cfg: dict[str, Any] = defaults.default_config("single_prompt", lang.code)
        cfg["prompt"] = "x"
        assert validate_pure("single_prompt", cfg).valid, lang.code


def test_defaults_inside_ranges_and_on_steps() -> None:
    cat = voice_catalog()
    config = defaults.default_config()
    for control in cat.controls:
        value: Any = config
        for part in control.path.strip("/").split("/"):
            value = value[part]
        number = Decimal(str(value))
        assert control.min <= number <= control.max, control.path
        assert control.on_step(number), control.path


def test_ambient_and_controls_unique() -> None:
    cat = voice_catalog()
    assert len(set(cat.ambient_ids())) == len(cat.ambient_ids()) == 7
    paths = [c.path for c in cat.controls]
    assert len(paths) == len(set(paths))
