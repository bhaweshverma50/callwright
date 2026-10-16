"""URL guard (003 T086, FR-040): blocked ranges, IPv6 forms, DNS rebinding, HTTPS rule."""

from __future__ import annotations

import httpx
import pytest

from app.core.url_guard import (
    UrlNotAllowed,
    check_url,
    guarded_request,
    is_blocked_ip,
    pinned_url,
)


def fixed(*addresses: str):  # type: ignore[no-untyped-def]
    async def resolver(host: str, port: int) -> list[str]:
        return list(addresses)

    return resolver


@pytest.mark.parametrize(
    "ip",
    [
        "10.0.0.1",
        "172.16.5.4",
        "192.168.1.1",
        "127.0.0.1",
        "169.254.169.254",  # cloud metadata
        "100.64.0.1",  # CGNAT
        "100.100.100.200",  # Alibaba metadata, inside CGNAT
        "0.0.0.0",  # noqa: S104 - a blocked address, not a bind
        "224.0.0.1",
        "::1",
        "fe80::1",
        "fd00:ec2::254",  # AWS metadata over IPv6
        "fc00::1",
        "::ffff:10.0.0.1",  # IPv4-mapped
        "::ffff:169.254.169.254",
        "64:ff9b::a00:1",  # NAT64
        "2002:a00:1::",  # 6to4 of 10.0.0.1
        "::",
    ],
)
def test_blocked_ranges(ip: str) -> None:
    assert is_blocked_ip(ip)


@pytest.mark.parametrize("ip", ["93.184.216.34", "8.8.8.8", "2606:4700:4700::1111"])
def test_public_addresses_allowed(ip: str) -> None:
    assert not is_blocked_ip(ip)


async def test_https_required_outside_development() -> None:
    with pytest.raises(UrlNotAllowed) as err:
        await check_url("http://example.com/hook", resolver=fixed("93.184.216.34"))
    assert err.value.reason == "https_required"
    ok = await check_url("http://example.com/hook", allow_http=True, resolver=fixed("93.184.216.34"))
    assert ok.port == 80


async def test_literal_private_ip_and_localhost_refused() -> None:
    for url in ("https://127.0.0.1/x", "https://[::1]/x", "https://localhost/x", "https://10.1.2.3:8443/"):
        with pytest.raises(UrlNotAllowed) as err:
            await check_url(url, resolver=fixed("93.184.216.34"))
        assert err.value.reason == "private_address"


async def test_any_private_answer_blocks_the_host() -> None:
    """DNS rebinding: one private answer among public ones is enough to refuse."""
    with pytest.raises(UrlNotAllowed):
        await check_url("https://rebind.example/hook", resolver=fixed("93.184.216.34", "10.0.0.7"))


async def test_resolution_failure_and_bad_urls() -> None:
    async def broken(host: str, port: int) -> list[str]:
        raise OSError("nxdomain")

    with pytest.raises(UrlNotAllowed) as err:
        await check_url("https://nope.example/", resolver=broken)
    assert err.value.reason == "dns_failure"
    for url in ("ftp://example.com/", "https:///nohost", "https://user:pw@example.com/"):
        with pytest.raises(UrlNotAllowed):
            await check_url(url, resolver=fixed("93.184.216.34"))


async def test_request_goes_to_the_checked_address_with_original_host() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(302, headers={"Location": "http://169.254.169.254/"})

    checked = await check_url("https://hooks.example.com:8443/in?x=1", resolver=fixed("93.184.216.34"))
    assert pinned_url(checked, "93.184.216.34") == "https://93.184.216.34:8443/in?x=1"
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        response = await guarded_request(client, "POST", checked, content=b"{}", timeout=3.0)
    assert response.status_code == 302  # redirects are not followed
    assert len(seen) == 1
    request = seen[0]
    assert request.url.host == "93.184.216.34"
    assert request.headers["host"] == "hooks.example.com:8443"
    assert request.extensions["sni_hostname"] == "hooks.example.com"
