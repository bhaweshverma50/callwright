"""Helpers for 022 tests: the shared fake Drive and the connect dance through the API."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from app.knowledge.sources.fake_drive import FakeDriveClient, shared_fake
from tests.conftest import Account


@pytest.fixture
def fake_drive() -> Iterator[FakeDriveClient]:
    drive = shared_fake()
    drive.reset()
    yield drive
    drive.reset()


async def start(
    client: httpx.AsyncClient, account: Account, connection_id: str | None = None
) -> dict[str, str]:
    body = {"connection_id": connection_id} if connection_id else {}
    response = await client.post("/v1/connections/google/start", json=body, headers=account.headers)
    assert response.status_code == 200, response.text
    query = parse_qs(urlsplit(response.json()["authorization_url"]).query)
    return {k: v[0] for k, v in query.items()}


async def complete(
    client: httpx.AsyncClient, account: Account, params: dict[str, str], *, code: str | None = None
) -> httpx.Response:
    body: dict[str, Any] = {"state": params["state"]}
    if "error" in params:
        body["error"] = params["error"]
    else:
        body["code"] = code or params.get("code", "fake-code")
    return await client.post("/v1/connections/google/complete", json=body, headers=account.headers)


async def connect(client: httpx.AsyncClient, account: Account, *, code: str | None = None) -> dict[str, Any]:
    response = await complete(client, account, await start(client, account), code=code)
    assert response.status_code in (200, 201), response.text
    body: dict[str, Any] = response.json()
    return body
