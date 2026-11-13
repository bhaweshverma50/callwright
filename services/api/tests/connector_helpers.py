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
    """The shared fake Drive, reset around the test. Synced folders start many ingestions at once,
    so the ingestion slot limit (2 per workspace, 5 s wait) is lifted for speed."""
    from app.knowledge import jobs

    drive = shared_fake()
    drive.reset()
    wait, slots = jobs.SLOT_WAIT_S, jobs.MAX_CONCURRENT_PER_WORKSPACE
    jobs.SLOT_WAIT_S, jobs.MAX_CONCURRENT_PER_WORKSPACE = 0.05, 64
    yield drive
    jobs.SLOT_WAIT_S, jobs.MAX_CONCURRENT_PER_WORKSPACE = wait, slots
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


async def make_kb(client: httpx.AsyncClient, account: Account, name: str = "Clinic policies") -> str:
    response = await client.post(
        "/v1/knowledge-bases",
        json={"name": name, "description": "Synced from Drive"},
        headers=account.headers,
    )
    assert response.status_code == 201, response.text
    kb_id: str = response.json()["id"]
    return kb_id


async def settle() -> None:
    """Wait for inline syncs and the ingestions they started (in-memory storage mode)."""
    from app.knowledge import jobs
    from app.knowledge.sources import jobs as sync_jobs

    for _ in range(5):
        await sync_jobs.drain()
        await jobs.drain()


async def add_source(
    client: httpx.AsyncClient,
    account: Account,
    kb_id: str,
    connection_id: str,
    root_id: str,
    **extra: Any,
) -> httpx.Response:
    body = {"connection_id": connection_id, "root_kind": "folder", "root_id": root_id, **extra}
    return await client.post(f"/v1/knowledge-bases/{kb_id}/sources", json=body, headers=account.headers)


async def synced_source(
    client: httpx.AsyncClient, account: Account, kb_id: str, connection_id: str, root_id: str, **extra: Any
) -> dict[str, Any]:
    response = await add_source(client, account, kb_id, connection_id, root_id, **extra)
    assert response.status_code == 201, response.text
    await settle()
    detail = await client.get(
        f"/v1/knowledge-bases/{kb_id}/sources/{response.json()['id']}", headers=account.headers
    )
    body: dict[str, Any] = detail.json()
    return body


async def documents(
    client: httpx.AsyncClient, account: Account, kb_id: str, status: str | None = None
) -> list[dict[str, Any]]:
    query = f"&status={status}" if status else ""
    response = await client.get(
        f"/v1/knowledge-bases/{kb_id}/documents?page_size=100{query}", headers=account.headers
    )
    assert response.status_code == 200, response.text
    items: list[dict[str, Any]] = response.json()["items"]
    return items


def node_id(drive: FakeDriveClient, name: str) -> str:
    return next(n.id for n in drive.nodes.values() if n.name == name and not n.trashed)


async def sync_now(app: Any, source_id: str, trigger: str = "manual") -> str | None:
    from app.knowledge.sources import jobs as sync_jobs

    run_id = await sync_jobs.run_now(app.state, source_id, trigger)
    await settle()
    return run_id


async def run_of(
    client: httpx.AsyncClient, account: Account, kb_id: str, source_id: str, run_id: str
) -> dict[str, Any]:
    response = await client.get(
        f"/v1/knowledge-bases/{kb_id}/sources/{source_id}/runs/{run_id}", headers=account.headers
    )
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


async def search(client: httpx.AsyncClient, account: Account, kb_id: str, query: str) -> list[dict[str, Any]]:
    response = await client.post(
        f"/v1/knowledge-bases/{kb_id}/search", json={"query": query}, headers=account.headers
    )
    assert response.status_code == 200, response.text
    results: list[dict[str, Any]] = response.json()["results"]
    return results
