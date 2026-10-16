"""contracts/templates.yaml (T068)."""

from __future__ import annotations

import httpx

from tests.conftest import Account
from tests.contract.conftest import check

WAV = b"RIFF\x24\x00\x00\x00WAVEfmt " + b"\x00" * 64
MP3 = b"ID3\x04\x00\x00\x00\x00\x00\x00" + b"\x00" * 64


async def test_templates_200_401_404(client: httpx.AsyncClient, account: Account) -> None:
    listed = check(await client.get("/v1/templates", headers=account.headers))
    assert listed.status_code == 200 and len(listed.json()["items"]) == 7
    health = check(
        await client.get("/v1/templates?category=healthcare&search=triage", headers=account.headers)
    )
    assert [t["id"] for t in health.json()["items"]] == ["healthcare-triage-booking"]
    categories = check(await client.get("/v1/templates/categories", headers=account.headers))
    assert [(c["id"], c["count"]) for c in categories.json()["items"]] == [
        ("automotive", 1),
        ("banking", 2),
        ("ecommerce", 1),
        ("healthcare", 2),
        ("telecom", 1),
    ]
    detail = check(await client.get("/v1/templates/banking-collections", headers=account.headers))
    assert detail.status_code == 200 and "{{customer_name}}" in detail.json()["config"]["prompt"]
    assert check(await client.get("/v1/templates")).status_code == 401
    assert check(await client.get("/v1/templates/categories")).status_code == 401
    assert check(await client.get("/v1/templates/banking-collections")).status_code == 401
    assert check(await client.get("/v1/templates/no-such-thing", headers=account.headers)).status_code == 404
