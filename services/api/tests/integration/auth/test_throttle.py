"""Sign-in throttling per account and per IP (T031, US1.2, R6)."""

from __future__ import annotations

import httpx
from fastapi import FastAPI

from tests.conftest import PASSWORD, make_client, signup


async def _sign_in(client: httpx.AsyncClient, email: str, password: str) -> httpx.Response:
    return await client.post("/v1/auth/sign-in", json={"email": email, "password": password})


async def test_five_failures_then_429(app: FastAPI) -> None:
    async with make_client(app, "10.1.0.1") as client:
        account = await signup(client, app)
        for _ in range(5):
            assert (await _sign_in(client, account.email, "wrong-pass-x")).status_code == 401
        blocked = await _sign_in(client, account.email, PASSWORD)
    assert blocked.status_code == 429
    body = blocked.json()
    assert body["code"] == "rate_limited"
    assert 0 < body["retry_after_s"] <= 900
    assert "minute" in body["detail"]
    assert blocked.headers["Retry-After"] == str(body["retry_after_s"])
    assert blocked.headers["content-type"].startswith("application/problem+json")


async def test_success_clears_the_account_counter(app: FastAPI) -> None:
    async with make_client(app, "10.1.0.2") as client:
        account = await signup(client, app)
        for _ in range(4):
            assert (await _sign_in(client, account.email, "wrong-pass-x")).status_code == 401
        assert (await _sign_in(client, account.email, PASSWORD)).status_code == 200
        for _ in range(4):
            assert (await _sign_in(client, account.email, "wrong-pass-x")).status_code == 401
        assert (await _sign_in(client, account.email, PASSWORD)).status_code == 200


async def test_unknown_email_counts_as_failure(app: FastAPI) -> None:
    async with make_client(app, "10.1.0.3") as client:
        response = await _sign_in(client, "nobody-here@example.com", "wrong-pass-x")
    assert response.status_code == 401
    assert response.json()["code"] == "invalid_credentials"


async def test_per_ip_limit_blocks_across_accounts(app: FastAPI) -> None:
    async with make_client(app, "10.1.0.4") as attacker:
        for i in range(20):
            response = await _sign_in(attacker, f"victim{i}@example.com", "wrong-pass-x")
            assert response.status_code == 401
        blocked = await _sign_in(attacker, "victim-new@example.com", "wrong-pass-x")
        assert blocked.status_code == 429
    async with make_client(app, "10.1.0.5") as other:
        account = await signup(other, app)
        assert (await _sign_in(other, account.email, PASSWORD)).status_code == 200
