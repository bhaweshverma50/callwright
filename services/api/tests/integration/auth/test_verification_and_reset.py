"""Unverified sign-in and password reset (T033, US1.4, R18)."""

from __future__ import annotations

import httpx
from fastapi import FastAPI

from tests.conftest import PASSWORD, latest_token, register, signup, unique_email


async def test_unverified_sign_in_is_403(client: httpx.AsyncClient, app: FastAPI) -> None:
    email = unique_email()
    await register(client, email)
    response = await client.post("/v1/auth/sign-in", json={"email": email, "password": PASSWORD})
    assert response.status_code == 403
    assert response.json()["code"] == "email_unverified"


async def test_resend_verification_sends_a_new_link(client: httpx.AsyncClient, app: FastAPI) -> None:
    email = unique_email()
    await register(client, email)
    first = latest_token(app, email, "verify_email")
    response = await client.post("/v1/auth/verify-email/resend", json={"email": email})
    assert response.status_code == 202
    assert latest_token(app, email, "verify_email") != first


async def test_reset_request_is_202_for_unknown_email(client: httpx.AsyncClient, app: FastAPI) -> None:
    email = unique_email("ghost")
    response = await client.post("/v1/auth/password-reset", json={"email": email})
    assert response.status_code == 202
    assert app.state.idp.latest_message(email, "recovery") is None


async def test_reset_flow_sets_password_once_and_revokes_sessions(
    client: httpx.AsyncClient, app: FastAPI
) -> None:
    account = await signup(client, app)
    assert (await client.post("/v1/auth/password-reset", json={"email": account.email})).status_code == 202
    token = latest_token(app, account.email, "recovery")
    new_password = "brand-new-password-7"
    confirm = await client.post(
        "/v1/auth/password-reset/confirm", json={"token_hash": token, "new_password": new_password}
    )
    assert confirm.status_code == 204
    assert (await client.get("/v1/me", headers=account.headers)).status_code == 401
    old = await client.post("/v1/auth/sign-in", json={"email": account.email, "password": PASSWORD})
    assert old.status_code == 401
    new = await client.post("/v1/auth/sign-in", json={"email": account.email, "password": new_password})
    assert new.status_code == 200
    reuse = await client.post(
        "/v1/auth/password-reset/confirm", json={"token_hash": token, "new_password": "third-password-11"}
    )
    assert reuse.status_code == 400
    assert reuse.json()["code"] == "invalid_link"


async def test_short_password_rejected(client: httpx.AsyncClient) -> None:
    response = await client.post("/v1/auth/register", json={"email": unique_email(), "password": "short"})
    assert response.status_code == 422
    errors = response.json()["errors"]
    assert errors[0]["pointer"] == "/password"
    assert errors[0]["code"] == "out_of_range"


async def test_sign_up_with_a_verified_email_mails_the_owner(client: httpx.AsyncClient, app: FastAPI) -> None:
    account = await signup(client, app)
    again = await client.post(
        "/v1/auth/register", json={"email": account.email, "password": "Other-pass-123!"}
    )
    assert again.status_code == 202  # the same answer as a new email: nothing reveals the account
    notices = [m for m in app.state.idp.outbox if m.to == account.email and m.kind == "account_exists"]
    assert len(notices) == 1
    assert notices[0].link.endswith("/login?email=" + account.email.replace("@", "%40"))
