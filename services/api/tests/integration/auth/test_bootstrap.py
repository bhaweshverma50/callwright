"""Verification bootstraps user, workspace and trial credit exactly once (T030, FR-002, R7)."""

from __future__ import annotations

import httpx
from fastapi import FastAPI
from sqlalchemy import select

from app.billing.models import CreditTransaction
from app.workspaces.models import Workspace
from tests.conftest import latest_token, register, signup, unique_email


async def test_verify_creates_workspace_and_trial_grant(client: httpx.AsyncClient, app: FastAPI) -> None:
    account = await signup(client, app)
    me = (await client.get("/v1/me", headers=account.headers)).json()
    assert me["user"]["email"] == account.email
    assert me["user"]["email_verified"] is True
    assert me["user"]["is_admin"] is False
    assert me["workspace"]["concurrency_limit"] == 5
    assert me["workspace"]["recording_default"] is True
    assert me["workspace"]["name"] == f"{account.email.split('@')[0]}'s workspace"
    assert me["balance_usd"] == "5.000000"
    async with app.state.db.transaction(workspace_id=account.workspace_id) as session:
        grants = list(
            (
                await session.execute(
                    select(CreditTransaction).where(CreditTransaction.workspace_id == account.workspace_id)
                )
            ).scalars()
        )
    assert [(g.type, str(g.amount_usd), g.seq) for g in grants] == [("trial_grant", "5.000000", 1)]


async def test_second_verification_is_a_no_op(client: httpx.AsyncClient, app: FastAPI) -> None:
    email = unique_email()
    await register(client, email)
    first_token = latest_token(app, email, "verify_email")
    await register(client, email)  # re-register before verifying: a new link is sent
    second_token = latest_token(app, email, "verify_email")
    assert first_token != second_token
    assert (await client.post("/v1/auth/verify-email", json={"token_hash": first_token})).status_code == 200
    second = await client.post("/v1/auth/verify-email", json={"token_hash": second_token})
    assert second.status_code == 200
    headers = {"Authorization": f"Bearer {second.json()['access_token']}"}
    me = (await client.get("/v1/me", headers=headers)).json()
    assert me["balance_usd"] == "5.000000"
    async with app.state.db.transaction(workspace_id=me["workspace"]["id"]) as session:
        count = len(
            list(
                (
                    await session.execute(
                        select(Workspace).where(Workspace.owner_user_id == me["user"]["id"])
                    )
                ).scalars()
            )
        )
    assert count == 1


async def test_used_link_is_rejected(client: httpx.AsyncClient, app: FastAPI) -> None:
    email = unique_email()
    await register(client, email)
    token = latest_token(app, email, "verify_email")
    assert (await client.post("/v1/auth/verify-email", json={"token_hash": token})).status_code == 200
    again = await client.post("/v1/auth/verify-email", json={"token_hash": token})
    assert again.status_code == 400
    assert again.json()["code"] == "invalid_link"


async def test_registering_a_verified_email_reveals_nothing(client: httpx.AsyncClient, app: FastAPI) -> None:
    account = await signup(client, app)
    response = await client.post(
        "/v1/auth/register", json={"email": account.email, "password": "another-password-1"}
    )
    assert response.status_code == 202
    assert response.json() == {"status": "verification_sent"}


async def test_refresh_issues_new_tokens(client: httpx.AsyncClient, app: FastAPI) -> None:
    account = await signup(client, app)
    refreshed = await client.post("/v1/auth/refresh", json={"refresh_token": account.refresh_token})
    assert refreshed.status_code == 200
    body = refreshed.json()
    assert body["token_type"] == "bearer" and body["expires_in"] > 0
    me = await client.get("/v1/me", headers={"Authorization": f"Bearer {body['access_token']}"})
    assert me.status_code == 200
    reused = await client.post("/v1/auth/refresh", json={"refresh_token": account.refresh_token})
    assert reused.status_code == 401
