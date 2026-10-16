"""Webhook address rules (T007, research R20)."""

from __future__ import annotations

import pytest

from app.agents.webhook_url import check_resolved, check_syntax, is_blocked_ip


@pytest.mark.parametrize(
    "url",
    [
        "https://hooks.example.com/callwright",
        "https://api.example.org:8443/x?y=1",
        "https://93.184.216.34/hook",
    ],
)
def test_public_https_accepted(url: str) -> None:
    assert check_syntax(url) is None


@pytest.mark.parametrize(
    ("url", "code"),
    [
        ("ftp://x", "invalid_format"),
        ("notaurl", "invalid_format"),
        ("http://hooks.example.com/x", "invalid_format"),
        ("https://user:pw@hooks.example.com/x", "invalid_format"),
        ("https://localhost/x", "private_address"),
        ("https://127.0.0.1/x", "private_address"),
        ("https://10.1.2.3/x", "private_address"),
        ("https://172.16.0.1/x", "private_address"),
        ("https://192.168.1.10/x", "private_address"),
        ("https://169.254.169.254/latest/meta-data", "private_address"),
        ("https://[::1]/x", "private_address"),
        ("https://[fd12:3456::1]/x", "private_address"),
        ("https://[fe80::1]/x", "private_address"),
        ("https://[::ffff:10.0.0.1]/x", "private_address"),
        ("https://metadata.google.internal/x", "private_address"),
        ("https://printer.local/x", "private_address"),
        ("https://intranet/x", "private_address"),
        ("https://100.64.1.1/x", "private_address"),
        ("https://" + "a" * 2050 + ".com", "out_of_range"),
    ],
)
def test_refused(url: str, code: str) -> None:
    issue = check_syntax(url)
    assert issue is not None and issue.code == code


def test_http_allowed_in_development() -> None:
    assert check_syntax("http://hooks.example.com/x", allow_http=True) is None
    assert check_syntax("http://127.0.0.1/x", allow_http=True) is not None


def test_blocked_ip_helper() -> None:
    assert is_blocked_ip("10.0.0.1") and is_blocked_ip("::1") and not is_blocked_ip("8.8.8.8")


async def test_resolved_host_checked() -> None:
    async def to_private(host: str) -> list[str]:
        return ["93.184.216.34", "192.168.0.5"]

    async def to_public(host: str) -> list[str]:
        return ["93.184.216.34"]

    async def fails(host: str) -> list[str]:
        raise OSError("no dns")

    url = "https://hooks.example.com/x"
    issue = await check_resolved(url, to_private)
    assert issue is not None and issue.code == "private_address"
    assert await check_resolved(url, to_public) is None
    assert await check_resolved(url, fails) is None
