"""Guarded webhook delivery (003 T086, FR-040): the request goes to the checked address."""

from __future__ import annotations

import httpx
from callwright_contract.url_guard import check_url

from app.core.url_guard import guarded_request


def fixed(*addresses: str):  # type: ignore[no-untyped-def]
    async def resolver(host: str, port: int) -> list[str]:
        return list(addresses)

    return resolver


async def test_request_goes_to_the_checked_address_with_original_host() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(302, headers={"Location": "http://169.254.169.254/"})

    checked = await check_url("https://hooks.example.com:8443/in?x=1", resolver=fixed("93.184.216.34"))
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        response = await guarded_request(client, "POST", checked, content=b"{}", timeout=3.0)
    assert response.status_code == 302  # redirects are not followed
    assert len(seen) == 1
    request = seen[0]
    assert request.url.host == "93.184.216.34"
    assert request.headers["host"] == "hooks.example.com:8443"
    assert request.extensions["sni_hostname"] == "hooks.example.com"
