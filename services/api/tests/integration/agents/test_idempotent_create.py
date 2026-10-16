"""Idempotent create and duplicate (T098, FR-038)."""

from __future__ import annotations

import asyncio

import httpx

from tests.agent_helpers import create, create_ok
from tests.conftest import Account


async def test_same_key_returns_same_agent(client: httpx.AsyncClient, account: Account) -> None:
    first = await create(client, account, name="Once", headers={"Idempotency-Key": "create-once-1"})
    second = await create(client, account, name="Once", headers={"Idempotency-Key": "create-once-1"})
    assert first.status_code == second.status_code == 201
    assert first.json()["id"] == second.json()["id"]
    other = await create(client, account, name="Once", headers={"Idempotency-Key": "create-once-2"})
    assert other.json()["id"] != first.json()["id"]
    listed = (await client.get("/v1/agents?search=Once", headers=account.headers)).json()
    assert listed["total"] == 2


async def test_concurrent_double_submit_creates_one(client: httpx.AsyncClient, account: Account) -> None:
    results = await asyncio.gather(
        *(
            create(client, account, name="Double click", headers={"Idempotency-Key": "dbl-1"})
            for _ in range(3)
        )
    )
    assert {r.status_code for r in results} == {201}
    assert len({r.json()["id"] for r in results}) == 1


async def test_duplicate_is_idempotent(client: httpx.AsyncClient, account: Account) -> None:
    agent = await create_ok(client, account, name="Dup source")
    url = f"/v1/agents/{agent['id']}/duplicate"
    headers = {**account.headers, "Idempotency-Key": "dup-1"}
    first, second = await asyncio.gather(client.post(url, headers=headers), client.post(url, headers=headers))
    assert first.json()["id"] == second.json()["id"]
    listed = (await client.get("/v1/agents?search=Dup source", headers=account.headers)).json()
    assert listed["total"] == 2


async def test_failed_create_releases_the_key(client: httpx.AsyncClient, account: Account) -> None:
    bad = await create(client, account, config={"prompt": ""}, headers={"Idempotency-Key": "retry-1"})
    assert bad.status_code == 422
    good = await create(client, account, headers={"Idempotency-Key": "retry-1"})
    assert good.status_code == 201
