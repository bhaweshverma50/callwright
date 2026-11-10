"""contracts/templates.yaml (T068)."""

from __future__ import annotations

import httpx

from tests.conftest import Account
from tests.contract.conftest import check

WAV = b"RIFF\x24\x00\x00\x00WAVEfmt " + b"\x00" * 64
MP3 = b"ID3\x04\x00\x00\x00\x00\x00\x00" + b"\x00" * 64


async def test_templates_200_401_404(client: httpx.AsyncClient, account: Account) -> None:
    listed = check(await client.get("/v1/templates", headers=account.headers))
    assert listed.status_code == 200 and len(listed.json()["items"]) == 26
    health = check(
        await client.get("/v1/templates?category=healthcare&search=triage", headers=account.headers)
    )
    assert [t["id"] for t in health.json()["items"]] == ["healthcare-triage-booking"]
    categories = check(await client.get("/v1/templates/categories", headers=account.headers))
    assert [(c["id"], c["count"]) for c in categories.json()["items"]] == [
        ("automotive", 3),
        ("banking", 5),
        ("ecommerce", 2),
        ("healthcare", 3),
        ("telecom", 3),
        ("insurance", 2),
        ("real_estate", 2),
        ("hospitality", 2),
        ("logistics", 2),
        ("utilities", 2),
    ]
    flows = check(
        await client.get("/v1/templates?agent_type=flow&direction=inbound", headers=account.headers)
    )
    assert {t["agent_type"] for t in flows.json()["items"]} == {"flow"}
    flow_counts = check(
        await client.get(
            "/v1/templates/categories?agent_type=flow&direction=inbound", headers=account.headers
        )
    )
    assert sum(c["count"] for c in flow_counts.json()["items"]) == len(flows.json()["items"])
    flow_detail = check(await client.get("/v1/templates/insurance-claim-intake", headers=account.headers))
    assert flow_detail.json()["agent_type"] == "flow" and flow_detail.json()["config"]["graph"]["nodes"]
    detail = check(await client.get("/v1/templates/banking-collections", headers=account.headers))
    assert detail.status_code == 200 and "{{customer_name}}" in detail.json()["config"]["prompt"]
    assert check(await client.get("/v1/templates")).status_code == 401
    assert check(await client.get("/v1/templates/categories")).status_code == 401
    assert check(await client.get("/v1/templates/banking-collections")).status_code == 401
    assert check(await client.get("/v1/templates/no-such-thing", headers=account.headers)).status_code == 404
