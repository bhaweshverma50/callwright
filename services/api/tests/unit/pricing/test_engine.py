"""Money tests for the pure pricing engine (T061, T090; SC-004, research R1 and R4)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.pricing import engine
from app.pricing.engine import Bundle, Catalog, Components, Rate, Selection, Usage

LLM_BUNDLES = (Bundle("llm_input_tokens", 20000), Bundle("llm_output_tokens", 200))
TTS_BUNDLES = (Bundle("tts_chars", 750),)


def _catalog() -> Catalog:
    return Catalog(
        version=1,
        effective_from=datetime(2026, 1, 1, tzinfo=UTC),
        rates=(
            Rate("stt", "deepgram", "nova-3", "Nova-3", Decimal("0.0085")),
            Rate("stt", "deepgram", None, "Deepgram, Auto", Decimal("0.0085")),
            Rate("llm", "azure_openai", "gpt-5-mini", "GPT-5 Mini", Decimal("0.0015"), LLM_BUNDLES),
            Rate("tts", "elevenlabs", "eleven_flash_v2_5", "Flash v2.5", Decimal("0.0450"), TTS_BUNDLES),
            Rate("nc", "sanas", "vi", "Voice isolation", Decimal("0.0000")),
            Rate("nc", "acme_nc", "pro", "Acme NC", Decimal("0.0020")),
            Rate("platform", "callwright", None, "Callwright platform fee", Decimal("0.0500")),
            Rate("embedding", "openai", "text-embedding-3-small", "Embedding", Decimal("0.000020"),
                 unit="k_tokens"),
        ),
    )


REFERENCE_COMPONENTS = Components(
    stt=Selection("deepgram", "nova-3"),
    llm=Selection("azure_openai", "gpt-5-mini"),
    tts=Selection("elevenlabs", "eleven_flash_v2_5"),
)
REFERENCE_USAGE = Usage(duration_ms=271_000, llm_input_tokens=102_348, llm_output_tokens=745, tts_chars=2_555)


def _line(quote: engine.Quote, component: str) -> engine.CostLine:
    assert quote.call is not None
    return next(line for line in quote.call.lines if line.component == component)


def test_reference_call_prices_to_0_477() -> None:
    quote = engine.price(REFERENCE_COMPONENTS, REFERENCE_USAGE, _catalog())
    assert quote.call is not None
    assert quote.call.total_usd == Decimal("0.477")
    costs = {line.component: line.cost_usd for line in quote.call.lines}
    assert costs == {
        "stt": Decimal("0.039"),
        "llm": Decimal("0.008"),
        "tts": Decimal("0.204"),
        "platform": Decimal("0.226"),
    }
    assert sum(costs.values()) == quote.call.total_usd


def test_reference_call_llm_surcharge_and_multiplier() -> None:
    quote = engine.price(REFERENCE_COMPONENTS, REFERENCE_USAGE, _catalog())
    llm = _line(quote, "llm")
    assert engine.fmt6(llm.billed_minutes) == "5.117400"
    assert engine.fmt6(llm.surcharge_usd) == "0.000901"
    assert llm.bundle_multiplier == Decimal("1.1330")
    meters = {m.unit: m for m in llm.meters}
    assert meters["llm_input_tokens"].used == 102_348
    assert meters["llm_input_tokens"].bundle_per_min == 20000
    assert engine.fmt6(meters["llm_input_tokens"].included) == "90333.333333"


def test_reference_call_tts_has_no_surcharge() -> None:
    quote = engine.price(REFERENCE_COMPONENTS, REFERENCE_USAGE, _catalog())
    tts = _line(quote, "tts")
    assert tts.surcharge_usd == 0
    assert tts.bundle_multiplier == Decimal("1.0000")
    assert engine.fmt6(tts.billed_minutes) == "4.516667"


def test_reference_call_duration_fields() -> None:
    quote = engine.price(REFERENCE_COMPONENTS, REFERENCE_USAGE, _catalog())
    assert quote.call is not None
    assert quote.call.billed_seconds == 271
    assert engine.fmt6(quote.call.duration_minutes) == "4.516667"
    assert quote.call.catalog_version == 1


def test_reference_call_raw_cost_excludes_platform_and_rounding() -> None:
    quote = engine.price(REFERENCE_COMPONENTS, REFERENCE_USAGE, _catalog())
    assert quote.call is not None
    # 0.0383917 + 0.0076761 + 0.2032500, unrounded, platform excluded (R14)
    assert quote.call.raw_cost_usd.quantize(Decimal("0.000001")) == Decimal("0.249318")


def test_4_2_second_call_bills_5_seconds() -> None:
    quote = engine.price(REFERENCE_COMPONENTS, Usage(duration_ms=4200), _catalog())
    assert quote.call is not None
    assert quote.call.billed_seconds == 5
    assert quote.call.duration_minutes == Decimal(5) / Decimal(60)


def test_whole_second_boundary_is_not_rounded_up() -> None:
    quote = engine.price(REFERENCE_COMPONENTS, Usage(duration_ms=5000), _catalog())
    assert quote.call is not None
    assert quote.call.billed_seconds == 5


def test_zero_duration_bills_nothing() -> None:
    usage = Usage(duration_ms=0, llm_input_tokens=50_000, tts_chars=900)
    quote = engine.price(REFERENCE_COMPONENTS, usage, _catalog())
    assert quote.call is not None
    assert quote.call.billed_seconds == 0
    assert quote.call.total_usd == 0
    assert all(line.cost_usd == 0 and line.billed_minutes == 0 for line in quote.call.lines)
    assert all(line.bundle_multiplier == Decimal("1.0000") for line in quote.call.lines)


def test_per_line_ceiling_never_under_bills() -> None:
    quote = engine.price(REFERENCE_COMPONENTS, Usage(duration_ms=1000), _catalog())
    assert quote.call is not None
    # 1 s of STT is 0.000141666 USD, billed as one tenth of a cent
    assert _line(quote, "stt").cost_usd == Decimal("0.001")


def test_output_token_bundle_can_drive_the_surcharge() -> None:
    usage = Usage(duration_ms=60_000, llm_input_tokens=1000, llm_output_tokens=400)
    llm = _line(engine.price(REFERENCE_COMPONENTS, usage, _catalog()), "llm")
    assert llm.billed_minutes == Decimal(2)
    assert llm.bundle_multiplier == Decimal("2.0000")
    assert llm.cost_usd == Decimal("0.003")


def test_nc_line_present_when_selected() -> None:
    components = Components(
        stt=REFERENCE_COMPONENTS.stt,
        llm=REFERENCE_COMPONENTS.llm,
        tts=REFERENCE_COMPONENTS.tts,
        nc=Selection("sanas", "vi"),
    )
    quote = engine.price(components, REFERENCE_USAGE, _catalog())
    nc = _line(quote, "nc")
    assert nc.cost_usd == 0
    assert quote.call is not None and quote.call.total_usd == Decimal("0.477")
    assert [line.component for line in quote.lines] == ["stt", "llm", "tts", "nc", "platform"]


def test_priced_nc_never_surcharges() -> None:
    components = Components(
        stt=REFERENCE_COMPONENTS.stt,
        llm=REFERENCE_COMPONENTS.llm,
        tts=REFERENCE_COMPONENTS.tts,
        nc=Selection("acme_nc", "pro"),
    )
    nc = _line(engine.price(components, REFERENCE_USAGE, _catalog()), "nc")
    assert nc.surcharge_usd == 0
    assert nc.cost_usd == Decimal("0.010")  # 0.002 x 4.516667 = 0.0090333, ceiling


def test_stt_and_platform_never_surcharge() -> None:
    usage = Usage(duration_ms=60_000, llm_input_tokens=10**7, llm_output_tokens=10**6, tts_chars=10**6)
    quote = engine.price(REFERENCE_COMPONENTS, usage, _catalog())
    for component in ("stt", "platform"):
        line = _line(quote, component)
        assert line.surcharge_usd == 0
        assert line.billed_minutes == Decimal(1)
        assert line.meters == ()


def test_per_minute_quote_without_usage() -> None:
    quote = engine.price(REFERENCE_COMPONENTS, None, _catalog())
    assert quote.call is None
    assert quote.complete is True
    assert quote.per_minute_total_usd == Decimal("0.1050")
    assert [line.component for line in quote.lines] == ["stt", "llm", "tts", "platform"]
    assert all(line.status == "priced" for line in quote.lines)


def test_provider_fallback_prices_unknown_model() -> None:
    components = Components(
        stt=Selection("deepgram", "nova-9"),
        llm=REFERENCE_COMPONENTS.llm,
        tts=REFERENCE_COMPONENTS.tts,
    )
    stt = next(line for line in engine.price(components, None, _catalog()).lines if line.component == "stt")
    assert stt.status == "priced"
    assert stt.rate_per_min_usd == Decimal("0.0085")
    assert stt.model == "nova-9"


def test_unpriced_line_is_reported_and_never_zero() -> None:
    components = Components(
        stt=REFERENCE_COMPONENTS.stt, llm=REFERENCE_COMPONENTS.llm, tts=Selection("not_a_vendor", None)
    )
    quote = engine.price(components, REFERENCE_USAGE, _catalog())
    tts = next(line for line in quote.lines if line.component == "tts")
    assert tts.status == "unpriced"
    assert tts.rate_per_min_usd is None
    assert quote.complete is False
    assert quote.per_minute_total_usd == Decimal("0.0600")
    assert quote.call is not None and quote.call.complete is False
    assert "tts" not in {line.component for line in quote.call.lines}


def test_ceil_money_steps() -> None:
    assert engine.ceil_money(Decimal("0.0380001")) == Decimal("0.039")
    assert engine.ceil_money(Decimal("0.038")) == Decimal("0.038")
    assert engine.ceil_money(Decimal("0")) == Decimal("0.000")


def test_embedding_priced_per_thousand_tokens() -> None:
    catalog = _catalog()
    rate = catalog.lookup("embedding", "openai", "text-embedding-3-small")
    assert rate is not None
    assert engine.price_embedding(rate, 1_000_000) == Decimal("0.020000")
    assert engine.price_embedding(rate, 1) == Decimal("0.000001")  # rounded up, never zero for usage
    assert engine.price_embedding(rate, 0) == Decimal("0")


def test_embedding_rejects_per_minute_rates() -> None:
    rate = _catalog().lookup("stt", "deepgram", "nova-3")
    assert rate is not None
    with pytest.raises(ValueError, match="k_tokens"):
        engine.price_embedding(rate, 10)


def test_negative_usage_rejected() -> None:
    with pytest.raises(ValueError):
        Usage(duration_ms=-1)
    with pytest.raises(ValueError):
        Usage(duration_ms=1000, tts_chars=-5)


# Feature keys (T090) ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("key", "family"),
    [
        ("calls", "calls"),
        ("flow_assistant", "flow_assistant"),
        ("voice_copilot", "voice_copilot"),
        ("analytics_chat", "analytics_chat"),
        ("prompt_generation", "prompt_generation"),
        ("post_call_analysis", "post_call_analysis"),
        ("embedding", "embedding"),
        ("eval.intent_fulfillment", "evaluations"),
        ("simulator.persona_turn", "simulations"),
        ("issues.cluster", "issues"),
        ("testing.run", "testing"),
    ],
)
def test_feature_keys_map_to_families(key: str, family: str) -> None:
    from app.pricing.features import feature_family

    assert feature_family(key) == family


@pytest.mark.parametrize("key", ["eval", "eval.", "unknown", "simulator.Bad", "calls.extra", ""])
def test_unregistered_feature_keys_rejected(key: str) -> None:
    from app.pricing.features import feature_family, is_valid_feature_key

    assert not is_valid_feature_key(key)
    with pytest.raises(ValueError):
        feature_family(key)


def test_every_family_is_in_the_usage_contract() -> None:
    from pathlib import Path

    import yaml

    from app.pricing.features import FAMILIES

    root = Path(__file__).resolve().parents[5]
    usage = yaml.safe_load((root / "specs/001-platform-foundation/contracts/usage.yaml").read_text())
    assert set(usage["components"]["schemas"]["FeatureFamily"]["enum"]) == set(FAMILIES)
