"""Launch catalog seed (T100, FR-022, SC-004): exactly the rows of data-model.md."""

from __future__ import annotations

from decimal import Decimal

from fastapi import FastAPI

from app.pricing import engine, service

LLM = (("llm_input_tokens", 20000), ("llm_output_tokens", 200))
TTS = (("tts_chars", 750),)

EXPECTED = {
    ("stt", "deepgram", None): ("0.0085", ()),
    ("stt", "deepgram", "nova-3"): ("0.0085", ()),
    ("stt", "deepgram", "nova-2"): ("0.0058", ()),
    ("stt", "deepgram", "flux-general-en"): ("0.0085", ()),
    ("stt", "assemblyai", None): ("0.0030", ()),
    ("stt", "assemblyai", "universal-streaming"): ("0.0030", ()),
    ("stt", "assemblyai", "universal-streaming-multilingual"): ("0.0030", ()),
    ("stt", "sarvam", None): ("0.0060", ()),
    ("stt", "sarvam", "saarika:v2.5"): ("0.0060", ()),
    ("stt", "sarvam", "saaras:v3"): ("0.0060", ()),
    ("llm", "azure_openai", "gpt-5-mini"): ("0.0015", LLM),
    ("llm", "azure_openai", "gpt-5.1"): ("0.0165", LLM),
    ("llm", "azure_openai", "gpt-5.2"): ("0.0315", LLM),
    ("llm", "openai", "gpt-5-mini"): ("0.0015", LLM),
    ("llm", "openai", "gpt-5.1"): ("0.0165", LLM),
    ("llm", "openai", "gpt-5.2"): ("0.0315", LLM),
    ("tts", "elevenlabs", "eleven_flash_v2_5"): ("0.0450", TTS),
    ("tts", "elevenlabs", "eleven_flash_v2"): ("0.0450", TTS),
    ("tts", "elevenlabs", "eleven_turbo_v2_5"): ("0.0450", TTS),
    ("tts", "elevenlabs", "eleven_turbo_v2"): ("0.0450", TTS),
    ("tts", "elevenlabs", "eleven_multilingual_v2"): ("0.0900", TTS),
    ("tts", "cartesia", "sonic-2"): ("0.0275", TTS),
    ("tts", "cartesia", "sonic-2-2025-03-07"): ("0.0275", TTS),
    ("tts", "cartesia", "sonic-3"): ("0.0275", TTS),
    ("tts", "cartesia", "sonic-turbo"): ("0.0275", TTS),
    ("tts", "fishaudio", "s2.1-pro"): ("0.0150", TTS),
    ("tts", "fishaudio", "s2-pro"): ("0.0150", TTS),
    ("tts", "fishaudio", "s1"): ("0.0150", TTS),
    ("nc", "sanas", "vi"): ("0.0000", ()),
    ("nc", "sanas", "st"): ("0.0000", ()),
    ("nc", "ai_coustics", "standard"): ("0.0000", ()),
    ("platform", "callwright", None): ("0.0500", ()),
    # Added to the version in effect by s003_0004 (003 T069), not part of the launch seed.
    ("llm", "anthropic", "claude-haiku-5-5"): ("0.0021", LLM),
    ("llm", "anthropic", "claude-sonnet-5-5"): ("0.0420", LLM),
}


def _live_capture() -> dict[str, object]:
    import json
    from pathlib import Path

    path = Path(__file__).resolve().parents[5] / "research/live/pricing-catalog.json"
    loaded: dict[str, object] = json.loads(path.read_text())
    return loaded


async def _v1(app: FastAPI) -> engine.Catalog:
    async with app.state.db.transaction() as session:
        return await service.catalog_version(session, 1)


async def test_v1_holds_exactly_the_32_launch_rows_plus_anthropic(app: FastAPI) -> None:
    catalog = await _v1(app)
    rows = {
        (r.component, r.provider, r.model): (
            r.rate_per_min_usd,
            tuple((b.unit, b.per_min) for b in r.bundles),
        )
        for r in catalog.call_rates()
    }
    assert len(catalog.call_rates()) == 34
    assert rows == {k: (Decimal(rate), bundles) for k, (rate, bundles) in EXPECTED.items()}


async def test_one_platform_row_and_free_noise_cancellation(app: FastAPI) -> None:
    catalog = await _v1(app)
    assert [r.rate_per_min_usd for r in catalog.rates if r.component == "platform"] == [Decimal("0.05")]
    assert all(r.rate_per_min_usd == 0 for r in catalog.rates if r.component == "nc")


async def test_embedding_rows_priced_per_thousand_tokens(app: FastAPI) -> None:
    catalog = await _v1(app)
    embeddings = [r for r in catalog.rates if r.component == "embedding"]
    assert {(r.provider, r.model) for r in embeddings} == {
        ("openai", "text-embedding-3-small"),
        ("azure_openai", "text-embedding-3-small"),
    }
    assert all(r.unit == "k_tokens" and r.rate_per_min_usd > 0 for r in embeddings)


async def test_reference_call_prices_to_0_477_with_seed_rates(app: FastAPI) -> None:
    components = engine.Components(
        stt=engine.Selection("deepgram", "nova-3"),
        llm=engine.Selection("azure_openai", "gpt-5-mini"),
        tts=engine.Selection("elevenlabs", "eleven_flash_v2_5"),
    )
    usage = engine.Usage(271_000, 102_348, 745, 2_555)
    quote = engine.price(components, usage, await _v1(app))
    assert quote.call is not None and quote.call.total_usd == Decimal("0.477")


async def test_seed_matches_the_live_capture(app: FastAPI) -> None:
    """Every rate in research/live/pricing-catalog.json appears in v1 (provider ids mapped)."""

    provider_map = {
        "azure": "azure_openai",
        "calldash": "callwright",
        "sanas_st": "sanas",
        "sanas_vi": "sanas",
    }
    live = _live_capture()
    catalog = await _v1(app)
    prices = {(r.component, r.provider): set() for r in catalog.call_rates()}
    for r in catalog.call_rates():
        prices[(r.component, r.provider)].add(r.rate_per_min_usd)
    matched = 0
    for component, rows in live.items():
        if not isinstance(rows, list):
            continue
        for row in rows:
            if row.get("component") not in {"stt", "llm", "tts", "nc", "platform"}:
                continue
            provider = provider_map.get(row["provider"], row["provider"])
            key = (row["component"], provider)
            if key not in prices:
                continue  # vendors the builder does not offer at launch (data-model.md)
            assert Decimal(str(row["price_per_min"])).quantize(Decimal("0.0001")) in {
                p.quantize(Decimal("0.0001")) for p in prices[key]
            }, (component, row)
            matched += 1
    assert matched == 32  # every offered option, "none" noise cancellation has no row
