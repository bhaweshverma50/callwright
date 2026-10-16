"""Speech catalog loading and the pricing join (T008, data-model 8.1, 8.3 to 8.6)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from app.pricing import engine
from app.voices.catalog import catalog_json, load_catalog

PRICING = engine.Catalog(
    version=1,
    effective_from=datetime(2026, 1, 1, tzinfo=UTC),
    rates=(
        engine.Rate("stt", "deepgram", None, "Auto", Decimal("0.0085")),
        engine.Rate("stt", "deepgram", "nova-2", "Nova-2", Decimal("0.0058")),
        engine.Rate(
            "tts", "cartesia", "sonic-2", "Sonic 2", Decimal("0.0275"), (engine.Bundle("tts_chars", 750),)
        ),
        engine.Rate("nc", "sanas", "vi", "Voice isolation", Decimal("0")),
    ),
)


def test_languages() -> None:
    cat = load_catalog()
    assert len(cat.languages) == 46
    assert cat.languages[0].code == "multi"
    assert cat.language("or") is not None and cat.language("od") is None


def test_per_language_defaults() -> None:
    cat = load_catalog()
    assert cat.stt_default_for("en-US") == {"provider": "deepgram", "model": None}
    assert cat.stt_default_for("ta") == {"provider": "sarvam", "model": None}
    assert cat.tts_default_for("en-US")["provider"] == "elevenlabs"
    assert cat.tts_default_for("de", "cartesia")["voice_id"] == "ac197a78-cec7-4c50-93e5-93bdc1910b11"
    assert cat.tts_default_for("de-AT", "cartesia")["voice_id"] == "ac197a78-cec7-4c50-93e5-93bdc1910b11"


def test_auto_rules() -> None:
    cat = load_catalog()
    assert cat.resolve_auto_stt("deepgram", "en-GB") == "nova-3"
    assert cat.resolve_auto_stt("deepgram", "fr") == "nova-2"
    assert cat.resolve_auto_stt("assemblyai", "es-419") == "universal-streaming-multilingual"
    assert cat.resolve_auto_stt("sarvam", "hi") == "saarika:v2.5"
    assert cat.resolve_auto_stt("nope", "en") is None


def test_pricing_join_and_null_price() -> None:
    body = catalog_json(PRICING)
    deepgram = next(p for p in body["stt"] if p["provider"] == "deepgram")
    assert deepgram["auto"]["price_per_min_usd"] == "0.008500"
    models = {m["id"]: m["price_per_min_usd"] for m in deepgram["models"]}
    assert models["nova-2"] == "0.005800"
    # nova-3 has no exact row here; the provider-level row prices it like the engine would.
    assert models["nova-3"] == "0.008500"
    sarvam = next(p for p in body["stt"] if p["provider"] == "sarvam")
    assert sarvam["auto"]["price_per_min_usd"] is None
    cartesia = next(p for p in body["tts"] if p["provider"] == "cartesia")
    sonic = next(m for m in cartesia["models"] if m["id"] == "sonic-2")
    assert sonic["price_per_min_usd"] == "0.027500" and sonic["chars_bundle_per_min"] == 750
    assert len(cartesia["default_voice_by_language"]) == 46
    nc = {(n["provider"], n["model"]): n for n in body["noise_cancellation"]}
    assert nc[("sanas", "vi")]["price_per_min_usd"] == "0.000000" and nc[("sanas", "vi")]["default"]
    assert nc[("sanas", "st")]["price_per_min_usd"] is None


def test_controls_and_ambient() -> None:
    body = catalog_json(None)
    assert {c["path"] for c in body["controls"]} >= {"/tts/speed", "/call_behavior/ring_duration_ms"}
    assert [s["id"] for s in body["ambient_sounds"]][:2] == ["office_ambience", "city_ambience"]
    assert len(body["ambient_sounds"]) == 7


def test_withdrawn_stt_model_hidden_but_resolvable() -> None:
    cat = load_catalog()
    from dataclasses import replace

    deepgram = cat.stt_provider("deepgram")
    assert deepgram is not None
    withdrawn = replace(
        deepgram, models=tuple(replace(m, withdrawn=m.id == "flux-general-en") for m in deepgram.models)
    )
    patched = replace(cat, stt=(withdrawn, *[p for p in cat.stt if p.provider != "deepgram"]))
    body = catalog_json(None, catalog=patched)
    ids = [m["id"] for m in next(p for p in body["stt"] if p["provider"] == "deepgram")["models"]]
    assert "flux-general-en" not in ids
    assert withdrawn.model("flux-general-en") is not None
    body = catalog_json(None, catalog=patched, include_withdrawn=True)
    ids = [m["id"] for m in next(p for p in body["stt"] if p["provider"] == "deepgram")["models"]]
    assert "flux-general-en" in ids
