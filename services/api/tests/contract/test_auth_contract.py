"""Every contracts/auth.yaml operation and documented status (T028)."""

from __future__ import annotations

import httpx
from fastapi import FastAPI

from tests.conftest import PASSWORD, latest_token, make_client, signup, unique_email
from tests.contract.conftest import check


async def test_register_202_and_422(client: httpx.AsyncClient) -> None:
    ok = check(await client.post("/v1/auth/register", json={"email": unique_email(), "password": PASSWORD}))
    assert ok.status_code == 202
    bad = check(await client.post("/v1/auth/register", json={"email": "not-an-email", "password": "x"}))
    assert bad.status_code == 422 and len(bad.json()["errors"]) == 2


async def test_register_200_with_auto_verify(client: httpx.AsyncClient, app: FastAPI) -> None:
    settings = app.state.settings
    app.state.settings = settings.model_copy(update={"auth_auto_verify_email": True})
    try:
        body = {"email": unique_email(), "password": PASSWORD}
        ok = check(await client.post("/v1/auth/register", json=body))
    finally:
        app.state.settings = settings
    assert ok.status_code == 200 and ok.json()["status"] == "signed_in"


async def test_register_429(app: FastAPI) -> None:
    settings = app.state.settings
    original = settings.auth_email_rate_limit_per_hour
    object.__setattr__(settings, "auth_email_rate_limit_per_hour", 1)
    try:
        async with make_client(app, "10.9.0.1") as client:
            check(
                await client.post("/v1/auth/register", json={"email": unique_email(), "password": PASSWORD})
            )
            limited = check(
                await client.post("/v1/auth/register", json={"email": unique_email(), "password": PASSWORD})
            )
            reset_limited = check(
                await client.post("/v1/auth/password-reset", json={"email": unique_email()})
            )
            resend_limited = check(
                await client.post("/v1/auth/verify-email/resend", json={"email": unique_email()})
            )
    finally:
        object.__setattr__(settings, "auth_email_rate_limit_per_hour", original)
    assert limited.status_code == reset_limited.status_code == resend_limited.status_code == 429


async def test_verify_email_200_and_400(client: httpx.AsyncClient, app: FastAPI) -> None:
    email = unique_email()
    await client.post("/v1/auth/register", json={"email": email, "password": PASSWORD})
    token = latest_token(app, email, "verify_email")
    assert check(await client.post("/v1/auth/verify-email", json={"token_hash": token})).status_code == 200
    assert check(await client.post("/v1/auth/verify-email", json={"token_hash": token})).status_code == 400


async def test_resend_202(client: httpx.AsyncClient) -> None:
    response = check(await client.post("/v1/auth/verify-email/resend", json={"email": unique_email()}))
    assert response.status_code == 202


async def test_sign_in_200_401_403_429(app: FastAPI) -> None:
    async with make_client(app, "10.9.0.2") as client:
        account = await signup(client, app)
        ok = check(await client.post("/v1/auth/sign-in", json={"email": account.email, "password": PASSWORD}))
        assert ok.status_code == 200
        unverified = unique_email()
        await client.post("/v1/auth/register", json={"email": unverified, "password": PASSWORD})
        forbidden = check(
            await client.post("/v1/auth/sign-in", json={"email": unverified, "password": PASSWORD})
        )
        assert forbidden.status_code == 403
        for _ in range(5):
            wrong = check(
                await client.post("/v1/auth/sign-in", json={"email": account.email, "password": "nope"})
            )
            assert wrong.status_code == 401
        limited = check(
            await client.post("/v1/auth/sign-in", json={"email": account.email, "password": "nope"})
        )
        assert limited.status_code == 429


async def test_refresh_200_401(client: httpx.AsyncClient, app: FastAPI) -> None:
    account = await signup(client, app)
    ok = check(await client.post("/v1/auth/refresh", json={"refresh_token": account.refresh_token}))
    assert ok.status_code == 200
    assert check(await client.post("/v1/auth/refresh", json={"refresh_token": "bogus"})).status_code == 401


async def test_sign_out_204_401(client: httpx.AsyncClient, app: FastAPI) -> None:
    account = await signup(client, app)
    assert check(await client.post("/v1/auth/sign-out", headers=account.headers)).status_code == 204
    assert check(await client.post("/v1/auth/sign-out", headers=account.headers)).status_code == 401


async def test_password_reset_202_and_confirm_204_400_422(client: httpx.AsyncClient, app: FastAPI) -> None:
    account = await signup(client, app)
    assert (
        check(await client.post("/v1/auth/password-reset", json={"email": account.email})).status_code == 202
    )
    token = latest_token(app, account.email, "recovery")
    short = check(
        await client.post("/v1/auth/password-reset/confirm", json={"token_hash": token, "new_password": "x"})
    )
    assert short.status_code == 422
    ok = check(
        await client.post(
            "/v1/auth/password-reset/confirm",
            json={"token_hash": token, "new_password": "another-password-1"},
        )
    )
    assert ok.status_code == 204
    used = check(
        await client.post(
            "/v1/auth/password-reset/confirm",
            json={"token_hash": token, "new_password": "another-password-2"},
        )
    )
    assert used.status_code == 400


async def test_change_password_200_401_422_429(app: FastAPI) -> None:
    async with make_client(app, "10.9.0.7") as client:
        account = await signup(client, app)
        new = "another-long-pass-3"
        bad = check(
            await client.post(
                "/v1/auth/password",
                json={"current_password": PASSWORD, "new_password": PASSWORD},
                headers=account.headers,
            )
        )
        assert bad.status_code == 422
        assert (
            check(
                await client.post(
                    "/v1/auth/password", json={"current_password": PASSWORD, "new_password": new}
                )
            ).status_code
            == 401
        )
        for _ in range(5):
            wrong = check(
                await client.post(
                    "/v1/auth/password",
                    json={"current_password": "wrong-pass-x", "new_password": new},
                    headers=account.headers,
                )
            )
            assert wrong.status_code == 401
        limited = check(
            await client.post(
                "/v1/auth/password",
                json={"current_password": PASSWORD, "new_password": new},
                headers=account.headers,
            )
        )
        assert limited.status_code == 429
    async with make_client(app, "10.9.0.8") as client:
        other = await signup(client, app)
        ok = check(
            await client.post(
                "/v1/auth/password",
                json={"current_password": PASSWORD, "new_password": new},
                headers=other.headers,
            )
        )
        assert ok.status_code == 200 and ok.json()["token_type"] == "bearer"
