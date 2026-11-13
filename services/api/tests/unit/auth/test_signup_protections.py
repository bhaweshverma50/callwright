"""Signup abuse protections: disposable domains, Turnstile, SMTP delivery (no network)."""

from __future__ import annotations

import logging
from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest
from pydantic import SecretStr

from app.auth import idp
from app.auth.captcha import verify_captcha
from app.auth.disposable import check_email_allowed
from app.core.errors import ProblemError
from tests.conftest import make_settings

TURNSTILE_PASS = "1x0000000000000000000000000000000AA"
TURNSTILE_FAIL = "2x0000000000000000000000000000000AA"


def test_blocked_disposable_domain() -> None:
    with pytest.raises(ProblemError) as caught:
        check_email_allowed(make_settings(), "a@mailinator.com")
    assert (caught.value.status, caught.value.code) == (400, "email_not_allowed")


def test_blocked_subdomain_matches_parent() -> None:
    with pytest.raises(ProblemError) as caught:
        check_email_allowed(make_settings(), "a@mail.mailinator.com")
    assert caught.value.code == "email_not_allowed"


def test_allowed_domain() -> None:
    check_email_allowed(make_settings(), "a@gmail.com")


def test_extra_domain_blocked_and_list_can_be_disabled() -> None:
    settings = make_settings(extra_blocked_email_domains=["Corp-Spam.example"])
    with pytest.raises(ProblemError) as caught:
        check_email_allowed(settings, "a@x.corp-spam.example")
    assert caught.value.code == "email_not_allowed"
    check_email_allowed(make_settings(block_disposable_email=False), "a@mailinator.com")


async def _captcha(secret: str | None, token: str | None, success: bool = True, boom: bool = False) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if boom:
            raise httpx.ConnectError("down")
        body = request.content.decode()
        assert "secret=" in body and "remoteip=1.2.3.4" in body
        return httpx.Response(200, json={"success": success})

    settings = make_settings(turnstile_secret_key=SecretStr(secret) if secret else None)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await verify_captcha(settings, token, "1.2.3.4", client)


async def test_captcha_skipped_without_secret() -> None:
    await _captcha(None, None)


async def test_captcha_passes() -> None:
    await _captcha(TURNSTILE_PASS, "tok")


async def test_captcha_rejected_token_and_missing_token() -> None:
    for token, success in (("tok", False), (None, True), ("", True)):
        with pytest.raises(ProblemError) as caught:
            await _captcha(TURNSTILE_FAIL, token, success)
        assert (caught.value.status, caught.value.code) == (400, "captcha_failed")


async def test_captcha_fails_closed_when_cloudflare_is_down() -> None:
    with pytest.raises(ProblemError) as caught:
        await _captcha(TURNSTILE_PASS, "tok", boom=True)
    assert caught.value.status == 503


class _FakeTx:
    async def __aenter__(self) -> Any:
        return MagicMock(execute=_noop)

    async def __aexit__(self, *exc: Any) -> None:
        return None


async def _noop(*args: Any, **kwargs: Any) -> None:
    return None


def _local(**overrides: Any) -> idp.LocalIdentityProvider:
    provider = idp.LocalIdentityProvider(make_settings(**overrides), MagicMock())
    provider.db.transaction = lambda *a, **k: _FakeTx()
    return provider


async def test_smtp_sends_link_and_keeps_outbox() -> None:
    provider = _local(
        smtp_host="smtp.example.com", smtp_username="u", smtp_password=SecretStr("pw"), smtp_from="a@x.test"
    )
    with patch("app.auth.idp.smtplib.SMTP") as smtp_cls:
        await provider._issue_token("u1", "ops@example.com", "verify_email")
    server = smtp_cls.return_value.__enter__.return_value
    smtp_cls.assert_called_once_with("smtp.example.com", 587, timeout=15)
    server.starttls.assert_called_once()
    server.login.assert_called_once_with("u", "pw")
    sent = server.send_message.call_args.args[0]
    assert sent["To"] == "ops@example.com" and provider.outbox[-1].link in sent.get_content()


async def test_smtp_failure_is_logged_masked_and_not_raised(caplog: pytest.LogCaptureFixture) -> None:
    provider = _local(smtp_host="smtp.example.com", smtp_password=SecretStr("hunter2"))
    with patch("app.auth.idp.smtplib.SMTP", side_effect=OSError("boom")), caplog.at_level(logging.WARNING):
        await provider._issue_token("u1", "ops@example.com", "verify_email")
    assert "o***@example.com" in caplog.text and "ops@example.com" not in caplog.text
    assert "hunter2" not in caplog.text and provider.outbox[-1].token_hash not in caplog.text
    assert len(provider.outbox) == 1
