"""Auto speech recognition (003 T116, FR-045): resolved per language from 002's speech catalog,
sent to the worker, and priced at the resolved model's rate."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.calls import components as comp
from app.pricing import engine
from app.pricing import service as pricing
from tests.runtime_support import Runtime, agent_config


@pytest.mark.parametrize(
    ("provider", "language", "model"),
    [
        ("deepgram", "en-US", "nova-3"),
        ("deepgram", "en-GB", "nova-3"),
        ("deepgram", "hi", "nova-2"),
        ("assemblyai", "en-US", "universal-streaming"),
        ("assemblyai", "es", "universal-streaming-multilingual"),
        ("assemblyai", "ja", None),
        ("sarvam", "hi", "saarika:v2.5"),
        ("acme", "en", None),
    ],
)
def test_resolution(provider: str, language: str, model: str | None) -> None:
    assert comp.auto_stt_model(provider, language) == model


def test_explicit_model_is_kept(runtime: Runtime) -> None:
    resolved = comp.resolve(
        agent_config(stt={"provider": "deepgram", "model": "flux-general-en"}), runtime.catalog
    )
    assert resolved.stt.model == "flux-general-en" and not resolved.stt_auto


async def test_deepgram_auto_in_hindi_is_priced_as_nova_2(runtime: Runtime) -> None:
    resolved = comp.resolve(agent_config(language="hi"), runtime.catalog)
    assert resolved.stt_auto and resolved.stt.model == "nova-2"
    async with runtime.db.transaction() as session:
        quote = await pricing.quote(
            session,
            resolved.pricing(),
            engine.Usage(duration_ms=60_000),
            at=datetime.now(UTC) - timedelta(seconds=1),
        )
    stt_line = next(line for line in quote.lines if line.component == "stt")
    assert stt_line.model == "nova-2" and stt_line.rate_per_min_usd == Decimal("0.0058")


def test_metered_model_wins_for_pricing(runtime: Runtime) -> None:
    resolved = comp.resolve(agent_config(), runtime.catalog)
    usage = {"stt": [{"provider": "deepgram", "model": "nova-2", "audio_ms": 1000}]}
    assert resolved.pricing(usage).stt.model == "nova-2"
    assert resolved.pricing().stt.model == "nova-3"


def test_auto_follows_the_agent_builder_rule(runtime: Runtime) -> None:
    """Auto resolves with 002's speech catalog (``VoiceCatalog.stt_auto_rules``): Nova-3 for
    Arabic, which the worker's old catalog rule sent to Nova-2."""
    resolved = comp.resolve(agent_config(language="ar"), runtime.catalog)
    assert resolved.stt_auto and resolved.stt.model == "nova-3"


def test_auto_model_must_cover_the_language(runtime: Runtime) -> None:
    # 002's rule falls back to the English model for Japanese, which does not list "ja".
    config = agent_config(language="ja", stt={"provider": "assemblyai", "model": None})
    resolved = comp.resolve(config, runtime.catalog)
    assert resolved.stt_auto and resolved.stt.model is None
    assert comp.unsupported(resolved, runtime.catalog) == "stt_language_unsupported:assemblyai/ja"
