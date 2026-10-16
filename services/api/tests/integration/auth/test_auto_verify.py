"""AUTH_AUTO_VERIFY_EMAIL (hosted demo without email delivery): registration signs straight in."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import httpx
import pytest
from fastapi import FastAPI

from tests.conftest import PASSWORD, register, signup, unique_email


@contextmanager
def _auto_verify(app: FastAPI) -> Iterator[None]:
    original = app.state.settings
    app.state.settings = original.model_copy(update={"auth_auto_verify_email": True})
    try:
        yield
    finally:
        app.state.settings = original


@pytest.fixture
def auto_verify(app: FastAPI) -> Iterator[None]:
    with _auto_verify(app):
        yield


async def _register(client: httpx.AsyncClient, email: str, password: str = PASSWORD) -> httpx.Response:
    return await client.post("/v1/auth/register", json={"email": email, "password": password})


async def test_register_returns_a_session_and_bootstraps_the_workspace(
    client: httpx.AsyncClient, app: FastAPI, auto_verify: None
) -> None:
    email = unique_email("auto")
    response = await _register(client, email)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "signed_in"
    assert body["token_type"] == "bearer"
    assert body["access_token"] and body["refresh_token"] and body["expires_in"] > 0
    me = await client.get("/v1/me", headers={"Authorization": f"Bearer {body['access_token']}"})
    assert me.status_code == 200, me.text
    assert me.json()["workspace"]["id"]
    assert app.state.idp.latest_message(email, "verify_email") is None
    again = await client.post("/v1/auth/sign-in", json={"email": email, "password": PASSWORD})
    assert again.status_code == 200


async def test_taken_email_with_another_password_answers_verification_sent(
    client: httpx.AsyncClient, app: FastAPI
) -> None:
    account = await signup(client, app)
    with _auto_verify(app):
        response = await _register(client, account.email, "a-different-password-1")
    assert response.status_code == 202
    assert response.json() == {"status": "verification_sent"}


async def test_unverified_account_is_confirmed_only_with_its_own_password(
    client: httpx.AsyncClient, app: FastAPI
) -> None:
    email = unique_email("pending")
    await register(client, email)  # auto-verify off: a normal unverified account
    with _auto_verify(app):
        wrong = await _register(client, email, "someone-elses-password")
        assert wrong.status_code == 202
        still = await client.post("/v1/auth/sign-in", json={"email": email, "password": PASSWORD})
        assert still.status_code == 403
        right = await _register(client, email)
        assert right.status_code == 200
        assert right.json()["status"] == "signed_in"


async def test_without_auto_verify_registration_is_unchanged(client: httpx.AsyncClient, app: FastAPI) -> None:
    email = unique_email()
    response = await _register(client, email)
    assert response.status_code == 202
    assert response.json() == {"status": "verification_sent"}
    assert app.state.idp.latest_message(email, "verify_email") is not None
