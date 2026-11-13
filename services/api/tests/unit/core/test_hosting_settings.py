"""Settings for hosted use: CORS from env, ENV aliases, staging, auto-verify guard, dev routes,
trusted proxy hops."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from starlette.requests import Request

from app.core.client_ip import client_ip
from app.core.config import Settings
from app.main import _log_hosting_flags, create_app
from tests.conftest import make_settings

REAL_SECRETS: dict[str, Any] = {
    "auth_jwt_secret": "a-real-jwt-secret-0123456789abcdef0123456789",
    "stripe_webhook_secret": "whsec_real",
    "secrets_master_key": "cmVhbC1tYXN0ZXIta2V5LTMyLWJ5dGVzLWxvbmctISE=",
    "service_token": "real-service-token",
    "livekit_api_secret": "real-livekit-secret",
}
PROD: dict[str, Any] = {
    **REAL_SECRETS,
    "env": "prod",
    "auth_provider": "supabase",
    "supabase_url": "https://example.supabase.co",
    "stripe_mode": "live",
    "stripe_secret_key": "sk_test_x",
}


def _settings(**values: Any) -> Settings:
    return Settings(_env_file=None, **values)  # type: ignore[call-arg]


def test_cors_origins_comma_separated_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CORS_ORIGINS", "https://callwright-one.vercel.app, http://localhost:5180/")
    assert _settings().cors_origins == ["https://callwright-one.vercel.app", "http://localhost:5180"]


def test_cors_origins_json_list_still_works(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CORS_ORIGINS", '["http://localhost:5180"]')
    assert _settings().cors_origins == ["http://localhost:5180"]


def test_env_production_is_an_alias_for_prod(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENV", "production")
    assert _settings(**{k: v for k, v in PROD.items() if k != "env"}).env == "prod"


def test_staging_refuses_dev_secrets_but_allows_demo_adapters() -> None:
    with pytest.raises(ValueError, match="staging settings use dev defaults"):
        _settings(env="staging")
    s = _settings(env="staging", livekit_mode="fake", **{k: v for k, v in REAL_SECRETS.items()})
    assert s.auth_provider == "local" and s.stripe_mode == "fake"


def test_auto_verify_is_refused_in_production_without_the_override() -> None:
    with pytest.raises(ValueError, match="ALLOW_AUTO_VERIFY_IN_PRODUCTION"):
        _settings(**PROD, auth_auto_verify_email=True)
    s = _settings(**PROD, auth_auto_verify_email=True, allow_auto_verify_in_production=True)
    assert s.auth_auto_verify_email


def test_auto_verify_logs_a_warning_at_startup(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level("WARNING", logger="app.main"):
        _log_hosting_flags(make_settings(auth_auto_verify_email=True))
    assert any("AUTH_AUTO_VERIFY_EMAIL is on" in r.getMessage() for r in caplog.records)


MAIL, CHECKOUT, STORAGE = "/v1/dev/mail", "/v1/dev/fake-checkout/cs_1", "/v1/dev/storage/k?expires=1&sig=x"


async def _paths(settings: Settings) -> set[str]:
    """Dev paths that are mounted. The app runs without its lifespan, so a mounted handler fails
    on missing state (500) while an unmounted path is a 404."""
    app = create_app(settings)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        return {p for p in (MAIL, CHECKOUT, STORAGE) if (await client.get(p)).status_code != 404}


async def test_dev_routes_default_on_for_dev_and_test() -> None:
    paths = await _paths(make_settings())
    assert {MAIL, CHECKOUT, STORAGE} <= paths


async def test_dev_routes_default_off_outside_dev_and_test() -> None:
    paths = await _paths(make_settings(env="staging", livekit_mode="fake", **REAL_SECRETS))
    assert not {MAIL, CHECKOUT, STORAGE} & paths


async def test_fake_checkout_can_be_on_while_mail_and_storage_are_off() -> None:
    settings = make_settings(env="staging", enable_fake_checkout=True, **REAL_SECRETS)
    assert settings.fake_checkout_enabled and not settings.dev_routes_enabled
    paths = await _paths(settings)
    assert CHECKOUT in paths
    assert not {MAIL, STORAGE} & paths


async def test_dev_routes_can_be_turned_off_in_dev() -> None:
    paths = await _paths(make_settings(enable_dev_routes=False))
    assert not {MAIL, CHECKOUT, STORAGE} & paths


def test_fake_checkout_needs_fake_stripe() -> None:
    settings = make_settings(enable_fake_checkout=True, stripe_mode="live", stripe_secret_key="sk_test_x")
    assert not settings.fake_checkout_enabled


def _request(hops: int, peer: str, forwarded: str | None) -> Request:
    headers = [(b"x-forwarded-for", forwarded.encode())] if forwarded is not None else []
    app = SimpleNamespace(state=SimpleNamespace(settings=SimpleNamespace(trusted_proxy_hops=hops)))
    return Request({"type": "http", "headers": headers, "client": (peer, 1234), "app": app})


@pytest.mark.parametrize(
    ("hops", "forwarded", "expected"),
    [
        (0, "6.6.6.6, 1.2.3.4", "169.254.1.1"),  # header ignored: socket peer
        (1, "6.6.6.6, 1.2.3.4", "1.2.3.4"),  # forged left-most entry is skipped
        (1, "1.2.3.4", "1.2.3.4"),
        (2, "6.6.6.6, 1.2.3.4, 35.191.0.1", "1.2.3.4"),  # behind a load balancer
        (2, "1.2.3.4", "1.2.3.4"),  # fewer entries than hops: the left-most
        (1, None, "169.254.1.1"),
    ],
)
def test_client_ip_reads_trusted_hops_from_the_right(hops: int, forwarded: str | None, expected: str) -> None:
    assert client_ip(_request(hops, "169.254.1.1", forwarded)) == expected


def test_production_refuses_the_fake_drive_and_reads_the_drive_switches() -> None:
    with pytest.raises(ValueError, match="CONNECTORS_DRIVE_MODE=fake"):
        _settings(**PROD, connectors_drive_mode="fake")
    s = _settings(**PROD, connectors_workspaces=" ws_a, ws_b ", connectors_sync_paused=True)
    assert s.connectors_enabled_for("ws_a") and not s.connectors_enabled_for("ws_c")
    assert s.connectors_sync_paused
    assert _settings(**PROD).connectors_enabled_for("ws_anything")
