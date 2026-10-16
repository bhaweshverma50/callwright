"""Cost card parity (T063, money test): the per-minute total from 001's quote equals the sum of
the catalog prices the pickers show plus the platform fee; an unpriced component makes the
quote incomplete and the version gets an ``unpriced`` publish blocker."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from app.pricing import engine
from app.pricing import service as pricing
from tests.agent_helpers import create_ok
from tests.conftest import Account

PLATFORM = Decimal("0.0500")


async def catalogs(client: httpx.AsyncClient, account: Account) -> tuple[dict[str, Any], dict[str, Any]]:
    llms = (await client.get("/v1/llms/catalog", headers=account.headers)).json()
    voices = (await client.get("/v1/voices/catalog", headers=account.headers)).json()
    return llms, voices


def picker_price(llms: dict[str, Any], voices: dict[str, Any], selection: dict[str, Any]) -> Decimal:
    llm = next(
        m["price_per_min_usd"]
        for p in llms["providers"]
        if p["id"] == selection["llm"]["provider"]
        for m in p["models"]
        if m["id"] == selection["llm"]["model"]
    )
    stt_provider = next(s for s in voices["stt"] if s["provider"] == selection["stt"]["provider"])
    stt = (
        stt_provider["auto"]["price_per_min_usd"]
        if selection["stt"]["model"] is None
        else next(
            m["price_per_min_usd"] for m in stt_provider["models"] if m["id"] == selection["stt"]["model"]
        )
    )
    tts = next(
        m["price_per_min_usd"]
        for t in voices["tts"]
        if t["provider"] == selection["tts"]["provider"]
        for m in t["models"]
        if m["id"] == selection["tts"]["model"]
    )
    total = Decimal(llm) + Decimal(stt) + Decimal(tts) + PLATFORM
    if selection.get("nc"):
        nc = next(
            n["price_per_min_usd"]
            for n in voices["noise_cancellation"]
            if (n["provider"], n["model"]) == (selection["nc"]["provider"], selection["nc"]["model"])
        )
        total += Decimal(nc)
    return total


SELECTIONS = {
    "default": {
        "stt": {"provider": "deepgram", "model": None},
        "llm": {"provider": "azure_openai", "model": "gpt-5.1"},
        "tts": {"provider": "elevenlabs", "model": "eleven_flash_v2_5"},
        "nc": {"provider": "sanas", "model": "vi"},
    },
    "nc_off": {
        "stt": {"provider": "deepgram", "model": "nova-2"},
        "llm": {"provider": "openai", "model": "gpt-5-mini"},
        "tts": {"provider": "cartesia", "model": "sonic-3"},
        "nc": None,
    },
    "premium": {
        "stt": {"provider": "sarvam", "model": "saaras:v3"},
        "llm": {"provider": "openai", "model": "gpt-5.2"},
        "tts": {"provider": "elevenlabs", "model": "eleven_multilingual_v2"},
        "nc": {"provider": "ai_coustics", "model": "standard"},
    },
}


@pytest.mark.parametrize("name", sorted(SELECTIONS))
async def test_quote_equals_picker_sum(client: httpx.AsyncClient, account: Account, name: str) -> None:
    selection = SELECTIONS[name]
    llms, voices = await catalogs(client, account)
    quote = await client.post("/v1/pricing/quote", json={"components": selection})
    assert quote.status_code == 200, quote.text
    body = quote.json()
    assert body["complete"] is True
    assert Decimal(body["per_minute_total_usd"]) == picker_price(llms, voices, selection)
    expected_lines = 5 if selection["nc"] else 4
    assert len(body["lines"]) == expected_lines


async def test_unpriced_component_incomplete_and_blocks_publish(
    client: httpx.AsyncClient, account: Account, app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = pricing.catalog_at

    async def without_cartesia(session: Any, at: Any = None) -> engine.Catalog:
        catalog = await real(session, at)
        return engine.Catalog(
            catalog.version,
            catalog.effective_from,
            tuple(r for r in catalog.rates if r.provider != "cartesia"),
        )

    monkeypatch.setattr(pricing, "catalog_at", without_cartesia)
    selection = SELECTIONS["nc_off"]
    quote = (await client.post("/v1/pricing/quote", json={"components": selection})).json()
    assert quote["complete"] is False
    voices = (await client.get("/v1/voices/catalog", headers=account.headers)).json()
    cartesia = next(t for t in voices["tts"] if t["provider"] == "cartesia")
    assert all(m["price_per_min_usd"] is None for m in cartesia["models"])
    agent = await create_ok(
        client,
        account,
        config={"prompt": "x", "tts": {"provider": "cartesia", "model": "sonic-3"}},
    )
    assert {"pointer": "/tts/model", "code": "unpriced"} in [
        {k: b[k] for k in ("pointer", "code")} for b in agent["publish_blockers"]
    ]
    published = await client.put(
        f"/v1/agents/{agent['id']}/published-version",
        json={"version_id": agent["draft_version"]["id"]},
        headers=account.headers,
    )
    assert published.status_code == 422 and published.json()["code"] == "publish_blocked"
    history = (await client.get(f"/v1/agents/{agent['id']}/versions", headers=account.headers)).json()
    assert history["items"][0]["has_publish_blockers"] is True
