"""contracts/llms.yaml (T026)."""

from __future__ import annotations

import httpx

from tests.conftest import Account
from tests.contract.conftest import check

WAV = b"RIFF\x24\x00\x00\x00WAVEfmt " + b"\x00" * 64
MP3 = b"ID3\x04\x00\x00\x00\x00\x00\x00" + b"\x00" * 64


async def test_llm_catalog_200_401(client: httpx.AsyncClient, account: Account) -> None:
    response = check(await client.get("/v1/llms/catalog", headers=account.headers))
    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, max-age=300"
    body = response.json()
    assert body["default"] == {"provider": "azure_openai", "model": "gpt-5.1"}
    prices = {(p["id"], m["id"]): m["price_per_min_usd"] for p in body["providers"] for m in p["models"]}
    assert (
        prices[("openai", "gpt-5.2")] == "0.031500" and prices[("azure_openai", "gpt-5-mini")] == "0.001500"
    )
    assert all(price is not None for price in prices.values())
    assert (
        check(
            await client.get("/v1/llms/catalog?include_withdrawn=true", headers=account.headers)
        ).status_code
        == 200
    )
    assert check(await client.get("/v1/llms/catalog")).status_code == 401
