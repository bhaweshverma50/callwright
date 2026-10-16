"""Supabase Auth adapter against a mocked GoTrue (no network)."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from app.auth import idp
from app.core.auth import TokenClaims
from tests.conftest import make_settings

SESSION = {
    "access_token": "at",
    "refresh_token": "rt",
    "expires_in": 3600,
    "user": {"id": "uuid-1", "email": "Ops@Example.com", "email_confirmed_at": "2026-10-16T00:00:00Z"},
}


def _adapter(handler: Any) -> tuple[idp.SupabaseIdentityProvider, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def record(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        result: httpx.Response = handler(request)
        return result

    client = httpx.AsyncClient(
        base_url="https://proj.supabase.co/auth/v1", transport=httpx.MockTransport(record)
    )
    settings = make_settings(
        auth_provider="supabase", supabase_url="https://proj.supabase.co", supabase_anon_key=SecretStr("anon")
    )
    return idp.SupabaseIdentityProvider(settings, client), seen


async def test_sign_in_maps_session() -> None:
    adapter, seen = _adapter(lambda r: httpx.Response(200, json=SESSION))
    session = await adapter.sign_in("ops@example.com", "pw-1234567890")
    assert session.user == idp.IdpUser("uuid-1", "ops@example.com", True)
    assert seen[0].url.path == "/auth/v1/token" and seen[0].url.params["grant_type"] == "password"
    assert seen[0].headers["apikey"] == "anon"


@pytest.mark.parametrize(
    ("body", "error"),
    [
        ({"error_code": "invalid_credentials"}, idp.InvalidCredentials),
        ({"error_code": "email_not_confirmed"}, idp.EmailNotConfirmed),
    ],
)
async def test_sign_in_errors(body: dict[str, str], error: type[Exception]) -> None:
    adapter, _ = _adapter(lambda r: httpx.Response(400, json=body))
    with pytest.raises(error):
        await adapter.sign_in("ops@example.com", "pw")


async def test_rate_limit_and_outage() -> None:
    limited, _ = _adapter(lambda r: httpx.Response(429, json={}))
    with pytest.raises(idp.IdpRateLimited):
        await limited.sign_up("a@example.com", "pw-1234567890")
    down, _ = _adapter(lambda r: httpx.Response(503, text="down"))
    with pytest.raises(idp.IdpUnavailable):
        await down.refresh("rt")


async def test_sign_up_swallows_existing_user() -> None:
    adapter, seen = _adapter(lambda r: httpx.Response(422, json={"error_code": "user_already_exists"}))
    await adapter.sign_up("a@example.com", "pw-1234567890")
    assert json.loads(seen[0].content) == {"email": "a@example.com", "password": "pw-1234567890"}


async def test_verify_uses_token_hash() -> None:
    adapter, seen = _adapter(lambda r: httpx.Response(200, json=SESSION))
    await adapter.verify_email("hash-1")
    assert json.loads(seen[0].content) == {"type": "email", "token_hash": "hash-1"}
    bad, _ = _adapter(lambda r: httpx.Response(403, json={"error_code": "otp_expired"}))
    with pytest.raises(idp.InvalidLink):
        await bad.verify_email("hash-1")


async def test_refresh_failure() -> None:
    adapter, _ = _adapter(lambda r: httpx.Response(400, json={"error_code": "refresh_token_not_found"}))
    with pytest.raises(idp.InvalidRefreshToken):
        await adapter.refresh("rt")


async def test_sign_out_is_global() -> None:
    adapter, seen = _adapter(lambda r: httpx.Response(204))
    await adapter.sign_out("at", TokenClaims("uuid-1", None, "sess", 0))
    assert seen[0].url.path == "/auth/v1/logout" and seen[0].url.params["scope"] == "global"
    assert seen[0].headers["authorization"] == "Bearer at"


async def test_password_reset_confirm_verifies_updates_and_signs_out() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/verify"):
            return httpx.Response(200, json=SESSION)
        return httpx.Response(200 if request.method == "PUT" else 204, json={})

    adapter, seen = _adapter(handler)
    assert await adapter.confirm_password_reset("hash-2", "new-password-123") == []
    assert [(r.method, r.url.path) for r in seen] == [
        ("POST", "/auth/v1/verify"),
        ("PUT", "/auth/v1/user"),
        ("POST", "/auth/v1/logout"),
    ]
    assert json.loads(seen[0].content) == {"type": "recovery", "token_hash": "hash-2"}


def test_build_idp_selects_adapter() -> None:
    settings = make_settings(auth_provider="supabase", supabase_url="https://proj.supabase.co")
    assert isinstance(idp.build_idp(settings, None), idp.SupabaseIdentityProvider)  # type: ignore[arg-type]


def test_supabase_requires_url() -> None:
    with pytest.raises(ValueError):
        make_settings(auth_provider="supabase")
