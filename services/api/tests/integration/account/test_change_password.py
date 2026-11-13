"""POST /v1/auth/password: change the password while signed in."""

from __future__ import annotations

import httpx
from fastapi import FastAPI

from app.workspaces.service import bootstrap_workspace
from tests.conftest import PASSWORD, Account, make_client, signup, unique_email

NEW_PASSWORD = "a-brand-new-pass-7"


async def _change(
    client: httpx.AsyncClient, account: Account, current: str, new: str = NEW_PASSWORD
) -> httpx.Response:
    return await client.post(
        "/v1/auth/password",
        json={"current_password": current, "new_password": new},
        headers=account.headers,
    )


async def _sign_in(client: httpx.AsyncClient, email: str, password: str) -> httpx.Response:
    return await client.post("/v1/auth/sign-in", json={"email": email, "password": password})


async def test_change_password_ends_every_other_session(client: httpx.AsyncClient, app: FastAPI) -> None:
    account = await signup(client, app)
    other = (await _sign_in(client, account.email, PASSWORD)).json()
    other_headers = {"Authorization": f"Bearer {other['access_token']}"}
    assert (await client.get("/v1/me", headers=other_headers)).status_code == 200

    response = await _change(client, account, PASSWORD)
    assert response.status_code == 200, response.text
    fresh = response.json()
    fresh_headers = {"Authorization": f"Bearer {fresh['access_token']}"}

    assert (await client.get("/v1/me", headers=fresh_headers)).status_code == 200
    for stale in (account.headers, other_headers):
        gone = await client.get("/v1/me", headers=stale)
        assert gone.status_code == 401 and gone.json()["code"] == "session_revoked"
    assert (
        await client.post("/v1/auth/refresh", json={"refresh_token": other["refresh_token"]})
    ).status_code == 401
    assert (await _sign_in(client, account.email, PASSWORD)).status_code == 401
    assert (await _sign_in(client, account.email, NEW_PASSWORD)).status_code == 200

    notice = app.state.idp.latest_message(account.email, "password_changed")
    assert notice is not None
    assert "UTC" in notice.body and "wasn't you" in notice.body and "/forgot-password" in notice.body


async def test_wrong_current_password_is_401_and_changes_nothing(
    client: httpx.AsyncClient, app: FastAPI
) -> None:
    account = await signup(client, app)
    response = await _change(client, account, "not-my-password")
    assert response.status_code == 401
    assert response.json()["code"] == "invalid_credentials"
    assert (await client.get("/v1/me", headers=account.headers)).status_code == 200
    assert (await _sign_in(client, account.email, PASSWORD)).status_code == 200
    assert app.state.idp.latest_message(account.email, "password_changed") is None


async def test_new_password_equal_to_current_is_422(client: httpx.AsyncClient, app: FastAPI) -> None:
    account = await signup(client, app)
    response = await _change(client, account, PASSWORD, PASSWORD)
    assert response.status_code == 422
    body = response.json()
    assert body["errors"][0]["pointer"] == "/new_password"
    assert body["errors"][0]["code"] == "same_as_current"


async def test_new_password_rules_match_registration(client: httpx.AsyncClient, app: FastAPI) -> None:
    account = await signup(client, app)
    assert (await _change(client, account, PASSWORD, "short")).status_code == 422
    assert (await _change(client, account, PASSWORD, "x" * 129)).status_code == 422


async def test_wrong_current_password_is_throttled_with_sign_in(app: FastAPI) -> None:
    async with make_client(app, "10.7.0.1") as client:
        account = await signup(client, app)
        for _ in range(5):
            assert (await _change(client, account, "wrong-pass-x")).status_code == 401
        blocked = await _change(client, account, PASSWORD)
        assert blocked.status_code == 429
        assert blocked.json()["code"] == "rate_limited"
        # The same per-account counter blocks signing in.
        assert (await _sign_in(client, account.email, PASSWORD)).status_code == 429


async def test_change_password_needs_a_session(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/v1/auth/password", json={"current_password": PASSWORD, "new_password": NEW_PASSWORD}
    )
    assert response.status_code == 401


async def test_google_only_account_reports_no_password_and_can_set_one(
    client: httpx.AsyncClient, app: FastAPI
) -> None:
    email = unique_email("google")
    session = await app.state.idp.sign_in_external(email)
    await bootstrap_workspace(
        app.state.db, app.state.settings, subject=session.user.subject, email=email, redis=app.state.redis
    )
    headers = {"Authorization": f"Bearer {session.access_token}"}
    me = (await client.get("/v1/me", headers=headers)).json()
    assert me["user"]["has_password"] is False

    # "Set a password" is the password-reset email; confirming it makes the account a password one.
    assert (await client.post("/v1/auth/password-reset", json={"email": email})).status_code == 202
    token = app.state.idp.latest_message(email, "recovery").token_hash
    assert (
        await client.post(
            "/v1/auth/password-reset/confirm", json={"token_hash": token, "new_password": NEW_PASSWORD}
        )
    ).status_code == 204
    signed_in = (await _sign_in(client, email, NEW_PASSWORD)).json()
    me = (await client.get("/v1/me", headers={"Authorization": f"Bearer {signed_in['access_token']}"})).json()
    assert me["user"]["has_password"] is True


async def test_password_account_reports_has_password(client: httpx.AsyncClient, app: FastAPI) -> None:
    account = await signup(client, app)
    me = (await client.get("/v1/me", headers=account.headers)).json()
    assert me["user"]["has_password"] is True
    assert me["user"]["deletion_scheduled_at"] is None
