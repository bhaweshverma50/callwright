"""Address guard on HTTP tool test runs (005 T037, research R4)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx
import pytest

from app.tools import http_exec

SPEC: dict[str, Any] = {
    "method": "POST",
    "url": "https://api.example.com/slots",
    "headers": [],
    "body_template": None,
    "timeout_ms": 2000,
    "response_mappings": [],
}


def resolver_for(table: dict[str, list[str]]) -> Callable[[str, int], Any]:
    async def resolve(host: str, port: int) -> list[str]:
        return table.get(host, ["93.184.216.34"])

    return resolve


async def run(
    handler: Callable[[httpx.Request], httpx.Response],
    *,
    url: str = SPEC["url"],
    table: dict[str, list[str]] | None = None,
    allow_http: bool = False,
) -> tuple[dict[str, Any], list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def record(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(record)) as client:
        result = await http_exec.run(
            {**SPEC, "url": url},
            {"date": "d"},
            {},
            client=client,
            allow_http=allow_http,
            resolver=resolver_for(table or {}),
        )
    return result, seen


def ok(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={"ok": True})


@pytest.mark.parametrize(
    "address",
    [
        "10.0.0.5",
        "172.16.0.1",
        "192.168.1.1",
        "127.0.0.1",
        "169.254.169.254",
        "100.64.0.1",
        "::1",
        "fd00:ec2::254",
    ],
)
async def test_private_and_metadata_addresses_are_blocked(address: str) -> None:
    result, seen = await run(ok, table={"api.example.com": [address]})
    assert result["is_error"] and result["error_code"] == "blocked_address"
    assert seen == []


async def test_literal_private_ip_is_blocked() -> None:
    result, seen = await run(ok, url="https://10.1.2.3/x")
    assert result["error_code"] == "blocked_address" and seen == []


async def test_connects_to_vetted_ip_with_original_host() -> None:
    result, seen = await run(ok)
    assert not result["is_error"]
    assert seen[0].url.host == "93.184.216.34"
    assert seen[0].headers["host"] == "api.example.com"
    assert seen[0].extensions["sni_hostname"] == "api.example.com"


async def test_dns_rebinding_any_private_answer_blocks() -> None:
    result, seen = await run(ok, table={"api.example.com": ["93.184.216.34", "10.0.0.7"]})
    assert result["error_code"] == "blocked_address" and seen == []


async def test_redirect_to_private_is_blocked() -> None:
    def redirect(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "https://evil.example.com/meta"})

    result, seen = await run(redirect, table={"evil.example.com": ["169.254.169.254"]})
    assert result["error_code"] == "blocked_address" and len(seen) == 1


async def test_redirects_followed_at_most_three_times() -> None:
    def loop(request: httpx.Request) -> httpx.Response:
        return httpx.Response(307, headers={"location": "https://api.example.com/again"})

    result, seen = await run(loop)
    assert len(seen) == 4 and result["http_status"] == 307


async def test_response_capped_at_64_kb() -> None:
    def big(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"x" * (70 * 1024))

    result, _ = await run(big)
    assert result["error_code"] == "response_too_large"
    assert len(result["response_body"]) == 64 * 1024


async def test_https_rule() -> None:
    result, seen = await run(ok, url="http://api.example.com/x")
    assert result["error_code"] == "blocked_address" and seen == []
    allowed, _ = await run(ok, url="http://api.example.com/x", allow_http=True)
    assert not allowed["is_error"]


async def test_upstream_status_and_timeout() -> None:
    result, _ = await run(lambda r: httpx.Response(503, text="down"))
    assert result["error_code"] == "http_status" and result["http_status"] == 503

    def slow(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    timed_out, _ = await run(slow)
    assert timed_out["error_code"] == "timeout"
