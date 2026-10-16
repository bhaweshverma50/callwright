"""Sign-out revokes the session everywhere (T032, US1.3, R8)."""

from __future__ import annotations

import httpx
from fastapi import FastAPI

from tests.conftest import signup


async def test_sign_out_revokes_access_and_refresh(client: httpx.AsyncClient, app: FastAPI) -> None:
    account = await signup(client, app)
    assert (await client.get("/v1/me", headers=account.headers)).status_code == 200
    out = await client.post("/v1/auth/sign-out", headers=account.headers)
    assert out.status_code == 204
    after = await client.get("/v1/me", headers=account.headers)
    assert after.status_code == 401
    assert after.json()["code"] == "session_revoked"
    refresh = await client.post("/v1/auth/refresh", json={"refresh_token": account.refresh_token})
    assert refresh.status_code == 401


async def test_sign_out_requires_a_token(client: httpx.AsyncClient) -> None:
    response = await client.post("/v1/auth/sign-out")
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"


async def test_garbage_and_expired_tokens_are_401(client: httpx.AsyncClient, app: FastAPI) -> None:
    import time

    import jwt

    garbage = await client.get("/v1/me", headers={"Authorization": "Bearer not-a-jwt"})
    assert garbage.status_code == 401 and garbage.json()["code"] == "invalid_token"
    secret = app.state.settings.auth_jwt_secret.get_secret_value()
    expired = jwt.encode(
        {"sub": "x", "aud": "authenticated", "exp": int(time.time()) - 60, "session_id": "s"},
        secret,
        algorithm="HS256",
    )
    response = await client.get("/v1/me", headers={"Authorization": f"Bearer {expired}"})
    assert response.status_code == 401 and response.json()["code"] == "token_expired"
    forged = jwt.encode(
        {"sub": "x", "aud": "authenticated", "exp": int(time.time()) + 60},
        "wrong-secret-0123456789abcdef0123",
        algorithm="HS256",
    )
    response = await client.get("/v1/me", headers={"Authorization": f"Bearer {forged}"})
    assert response.status_code == 401


async def test_valid_token_for_unknown_user_is_401_not_403(client: httpx.AsyncClient, app: FastAPI) -> None:
    """A correctly signed token whose user no longer exists (deleted account, reset database) is a
    dead session: 401 lets the web client refresh or sign out instead of looping on 403."""
    import time
    import uuid

    import jwt

    secret = app.state.settings.auth_jwt_secret.get_secret_value()
    token = jwt.encode(
        {
            "sub": str(uuid.uuid4()),
            "aud": "authenticated",
            "exp": int(time.time()) + 600,
            "session_id": str(uuid.uuid4()),
        },
        secret,
        algorithm="HS256",
    )
    response = await client.get("/v1/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401
    assert response.json()["code"] == "session_invalid"
