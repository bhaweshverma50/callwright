"""contracts/core.yaml: health (T021)."""

from __future__ import annotations

import httpx

from tests.contract.conftest import check


async def test_health(client: httpx.AsyncClient) -> None:
    body = check(await client.get("/v1/health")).json()
    assert body["status"] == "ok"
