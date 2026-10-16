"""contracts/pricing.yaml (T063): catalog, quotes, admin versions with 403 for non-admins."""

from __future__ import annotations

from datetime import datetime, timedelta

import httpx
from fastapi import FastAPI

from tests.conftest import Account, make_admin, make_client
from tests.contract.conftest import check

REFERENCE = {
    "components": {
        "stt": {"provider": "deepgram", "model": "nova-3"},
        "llm": {"provider": "azure_openai", "model": "gpt-5-mini"},
        "tts": {"provider": "elevenlabs", "model": "eleven_flash_v2_5"},
        "nc": None,
    },
    "usage": {"duration_ms": 271000, "llm_input_tokens": 102348, "llm_output_tokens": 745, "tts_chars": 2555},
}


async def test_catalog(client: httpx.AsyncClient) -> None:
    response = check(await client.get("/v1/pricing/catalog"))
    assert response.headers["cache-control"] == "public, max-age=300"
    body = response.json()
    assert body["version"] == 1 and len(body["entries"]) == 32
    pinned = check(await client.get("/v1/pricing/catalog?at=2026-06-01T00:00:00Z"))
    assert pinned.json()["version"] == 1


async def test_quote_with_usage_is_the_reference_call(client: httpx.AsyncClient) -> None:
    body = check(await client.post("/v1/pricing/quote", json=REFERENCE)).json()
    call = body["call"]
    assert call["total_usd"] == "0.477000"
    assert call["billed_seconds"] == 271 and call["duration_minutes"] == "4.516667"
    rows = [
        (x["component"], x["billed_minutes"], x["cost_usd"], x["surcharge_usd"], x["bundle_multiplier"])
        for x in call["lines"]
    ]
    assert rows == [
        ("stt", "4.516667", "0.039000", "0.000000", "1.0000"),
        ("llm", "5.117400", "0.008000", "0.000901", "1.1330"),
        ("tts", "4.516667", "0.204000", "0.000000", "1.0000"),
        ("platform", "4.516667", "0.226000", "0.000000", "1.0000"),
    ]


async def test_quote_without_usage_and_unpriced(client: httpx.AsyncClient) -> None:
    per_minute = check(await client.post("/v1/pricing/quote", json={"components": REFERENCE["components"]}))
    body = per_minute.json()
    assert "call" not in body and body["per_minute_total_usd"] == "0.105000" and body["complete"] is True
    unpriced = dict(REFERENCE["components"]) | {"tts": {"provider": "not_a_vendor"}}  # type: ignore[operator]
    body = check(await client.post("/v1/pricing/quote", json={"components": unpriced})).json()
    tts = next(line for line in body["lines"] if line["component"] == "tts")
    assert tts["status"] == "unpriced" and tts["rate_per_min_usd"] is None and body["complete"] is False
    short = check(await client.post("/v1/pricing/quote", json={"components": {"stt": {"provider": "x"}}}))
    assert short.status_code == 422
    rounded = check(
        await client.post(
            "/v1/pricing/quote", json={"components": REFERENCE["components"], "usage": {"duration_ms": 4200}}
        )
    )
    assert rounded.json()["call"]["billed_seconds"] == 5


async def test_quote_rate_limited(app: FastAPI) -> None:
    async with make_client(app, "10.8.0.1") as client:
        statuses = [
            (await client.post("/v1/pricing/quote", json={"components": REFERENCE["components"]})).status_code
            for _ in range(61)
        ]
        limited = check(await client.post("/v1/pricing/quote", json={"components": REFERENCE["components"]}))
    assert statuses[:60] == [200] * 60 and statuses[60] == 429
    assert limited.status_code == 429 and limited.json()["retry_after_s"] >= 1


async def test_admin_versions_401_403(client: httpx.AsyncClient, account: Account) -> None:
    assert check(await client.get("/v1/admin/pricing/versions")).status_code == 401
    assert check(await client.get("/v1/admin/pricing/versions", headers=account.headers)).status_code == 403
    body = {"effective_from": "2100-01-01T00:00:00Z", "entries": []}
    assert check(await client.post("/v1/admin/pricing/versions", json=body)).status_code == 401
    forbidden = check(await client.post("/v1/admin/pricing/versions", json=body, headers=account.headers))
    assert forbidden.status_code == 403


async def test_admin_publish_and_list(
    client: httpx.AsyncClient, account: Account, future_catalog: int
) -> None:
    await make_admin(account)
    listed = check(await client.get("/v1/admin/pricing/versions", headers=account.headers)).json()
    latest = datetime.fromisoformat(listed["items"][0]["effective_from"])
    catalog = check(await client.get("/v1/pricing/catalog")).json()
    entries = [
        e | ({"rate_per_min_usd": "0.017000"} if e["component"] == "stt" else {}) for e in catalog["entries"]
    ]
    effective = (latest + timedelta(days=30)).isoformat()
    published = check(
        await client.post(
            "/v1/admin/pricing/versions",
            json={"effective_from": effective, "entries": entries, "notes": "STT x2"},
            headers=account.headers,
        )
    )
    assert published.status_code == 201
    assert published.json()["version"] == listed["total"] + 1
    again = check(await client.get("/v1/admin/pricing/versions", headers=account.headers)).json()
    assert again["items"][0]["version"] == published.json()["version"]
    assert again["items"][1]["effective_to"] == again["items"][0]["effective_from"]
    past = check(
        await client.post(
            "/v1/admin/pricing/versions",
            json={"effective_from": "2020-01-01T00:00:00Z", "entries": entries},
            headers=account.headers,
        )
    )
    assert past.status_code == 422
    no_platform = [e for e in entries if e["component"] != "platform"]
    invalid = check(
        await client.post(
            "/v1/admin/pricing/versions",
            json={"effective_from": "2200-01-01T00:00:00Z", "entries": no_platform},
            headers=account.headers,
        )
    )
    assert invalid.status_code == 422
    still_v1 = check(await client.post("/v1/pricing/quote", json=REFERENCE)).json()
    assert still_v1["catalog_version"] == 1
