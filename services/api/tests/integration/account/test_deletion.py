"""POST/DELETE /v1/account/deletion: schedule with a 30-day grace period, lock, cancel."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
from fastapi import FastAPI

from app.workspaces.service import bootstrap_workspace
from tests.conftest import PASSWORD, Account, make_client, signup, unique_email
from tests.runtime_support import owner_sql


async def _workspace_name(client: httpx.AsyncClient, account: Account) -> str:
    me = (await client.get("/v1/me", headers=account.headers)).json()
    name: str = me["workspace"]["name"]
    return name


async def _schedule(client: httpx.AsyncClient, account: Account, name: str, **extra: str) -> httpx.Response:
    return await client.post(
        "/v1/account/deletion",
        json={"confirm_workspace_name": name, **extra},
        headers=account.headers,
    )


async def _sign_in(client: httpx.AsyncClient, email: str, password: str = PASSWORD) -> dict[str, str]:
    response = await client.post("/v1/auth/sign-in", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    body: dict[str, str] = response.json()
    return body


async def test_wrong_workspace_name_is_422(client: httpx.AsyncClient, app: FastAPI) -> None:
    account = await signup(client, app)
    name = await _workspace_name(client, account)
    for typed in ("", "Something else", name.upper(), name + " "):
        response = await _schedule(client, account, typed, password=PASSWORD)
        assert response.status_code == 422, typed
        assert response.json()["errors"][0]["pointer"] == "/confirm_workspace_name"
    assert (await client.get("/v1/agents", headers=account.headers)).status_code == 200


async def test_wrong_or_missing_password(app: FastAPI) -> None:
    async with make_client(app, "10.7.1.1") as client:
        account = await signup(client, app)
        name = await _workspace_name(client, account)
        missing = await _schedule(client, account, name)
        assert missing.status_code == 422 and missing.json()["errors"][0]["pointer"] == "/password"
        wrong = await _schedule(client, account, name, password="not-my-password")
        assert wrong.status_code == 401 and wrong.json()["code"] == "invalid_credentials"
        assert (await client.get("/v1/agents", headers=account.headers)).status_code == 200


async def test_wrong_passwords_are_throttled_like_sign_in(app: FastAPI) -> None:
    async with make_client(app, "10.7.1.2") as client:
        account = await signup(client, app)
        name = await _workspace_name(client, account)
        for _ in range(5):
            assert (await _schedule(client, account, name, password="wrong-pass-x")).status_code == 401
        blocked = await _schedule(client, account, name, password=PASSWORD)
        assert blocked.status_code == 429 and blocked.json()["code"] == "rate_limited"


async def test_schedule_locks_the_account_and_cancel_restores_it(
    client: httpx.AsyncClient, app: FastAPI
) -> None:
    account = await signup(client, app)
    name = await _workspace_name(client, account)
    before = datetime.now(UTC)

    response = await _schedule(client, account, name, password=PASSWORD)
    assert response.status_code == 202, response.text
    scheduled = datetime.fromisoformat(response.json()["scheduled_at"])
    assert timedelta(days=29, hours=23) < scheduled - before < timedelta(days=30, minutes=1)

    mail = app.state.idp.latest_message(account.email, "deletion_scheduled")
    assert mail is not None
    assert f"{scheduled.strftime('%B')} {scheduled.day}, {scheduled.year}" in mail.body
    assert "Keep my account" in mail.body

    # Every session ended, including the one that asked.
    ended = await client.get("/v1/me", headers=account.headers)
    assert ended.status_code == 401 and ended.json()["code"] == "session_revoked"
    assert (
        await client.post("/v1/auth/refresh", json={"refresh_token": account.refresh_token})
    ).status_code == 401

    # Sign-in still works, but the account is locked.
    tokens = await _sign_in(client, account.email)
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    me = await client.get("/v1/me", headers=headers)
    assert me.status_code == 200
    assert datetime.fromisoformat(me.json()["user"]["deletion_scheduled_at"]) == scheduled
    for method, path in (
        ("GET", "/v1/agents"),
        ("GET", "/v1/calls"),
        ("GET", "/v1/billing/balance"),
        ("PATCH", "/v1/workspaces/current"),
        ("POST", "/v1/account/deletion"),
        ("POST", "/v1/auth/password"),
    ):
        locked = await client.request(method, path, json={"name": "x"}, headers=headers)
        assert locked.status_code == 403, (method, path, locked.text)
        assert locked.json()["code"] == "account_deletion_scheduled", (method, path)

    # Refresh and sign-out still work while locked.
    refreshed = await client.post("/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert refreshed.status_code == 200
    headers = {"Authorization": f"Bearer {refreshed.json()['access_token']}"}

    cancel = await client.delete("/v1/account/deletion", headers=headers)
    assert cancel.status_code == 204
    assert app.state.idp.latest_message(account.email, "deletion_cancelled") is not None
    assert (await client.get("/v1/agents", headers=headers)).status_code == 200
    me = (await client.get("/v1/me", headers=headers)).json()
    assert me["user"]["deletion_scheduled_at"] is None
    assert owner_sql("select deletion_requested_at from users where id = %s", (account.user_id,)) == [(None,)]


async def test_sign_out_works_while_scheduled(client: httpx.AsyncClient, app: FastAPI) -> None:
    account = await signup(client, app)
    name = await _workspace_name(client, account)
    assert (await _schedule(client, account, name, password=PASSWORD)).status_code == 202
    tokens = await _sign_in(client, account.email)
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    assert (await client.post("/v1/auth/sign-out", headers=headers)).status_code == 204


async def test_google_only_account_confirms_with_its_email(client: httpx.AsyncClient, app: FastAPI) -> None:
    email = unique_email("google")
    session = await app.state.idp.sign_in_external(email)
    await bootstrap_workspace(
        app.state.db, app.state.settings, subject=session.user.subject, email=email, redis=app.state.redis
    )
    headers = {"Authorization": f"Bearer {session.access_token}"}
    me = (await client.get("/v1/me", headers=headers)).json()
    account = Account(
        email, "", session.access_token, session.refresh_token, me["user"]["id"], me["workspace"]["id"]
    )
    name = me["workspace"]["name"]

    # A password is not what this account has: the email is the confirmation.
    for extra in ({}, {"confirm_email": "someone-else@example.com"}, {"password": PASSWORD}):
        response = await _schedule(client, account, name, **extra)
        assert response.status_code == 422, extra
    ok = await _schedule(client, account, name, confirm_email=email.upper())
    assert ok.status_code == 202, ok.text
