"""CSV export cap (006 T090, FR-035)."""

from __future__ import annotations

import httpx
import pytest

from app.calls import read_router
from tests.calls_support import SeededCalls


async def test_export_too_large(
    client: httpx.AsyncClient, seeded_calls: SeededCalls, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(read_router, "EXPORT_LIMIT", 10)
    response = await client.get("/v1/calls/export", headers=seeded_calls.a.headers)
    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "export_too_large"
    assert body["limit"] == 10 and body["total"] == 45
    assert "narrow the filters" in body["detail"]


async def test_export_same_rows_as_list(client: httpx.AsyncClient, seeded_calls: SeededCalls) -> None:
    h = seeded_calls.a.headers
    listed = (await client.get("/v1/calls", params={"page_size": 100, "sort": "cost_usd"}, headers=h)).json()[
        "items"
    ]
    lines = (
        await client.get("/v1/calls/export", params={"sort": "cost_usd", "columns": "call_id"}, headers=h)
    ).text.splitlines()
    assert lines[1:] == [i["call_id"] for i in listed]
