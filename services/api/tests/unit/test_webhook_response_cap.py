"""A webhook receiver cannot make delivery buffer an unbounded response body."""

from __future__ import annotations

import httpx

from app.webhooks_out import jobs


async def _send(handler: httpx.MockTransport) -> jobs.AttemptResult:
    async def resolver(host: str, port: int) -> list[str]:
        return ["93.184.216.34"]

    async with httpx.AsyncClient(transport=handler) as client:
        return await jobs.send_once(
            client,
            "https://hooks.example.com/in",
            b"{}",
            {},
            5000,
            allow_http=False,
            allow_private=False,
            resolver=resolver,
        )


async def test_large_response_is_cut_and_excerpted() -> None:
    pulled = 0

    async def body() -> object:
        nonlocal pulled
        for _ in range(10_000):
            pulled += 1024
            yield b"x" * 1024

    transport = httpx.MockTransport(lambda request: httpx.Response(200, content=body()))
    result = await _send(transport)
    assert result.status_code == 200 and result.error is None
    assert result.response_excerpt == "x" * jobs.EXCERPT_CHARS
    assert pulled <= jobs.MAX_RESPONSE_BYTES + 1024


async def test_small_response_is_unchanged() -> None:
    result = await _send(httpx.MockTransport(lambda request: httpx.Response(500, text="boom")))
    assert result.status_code == 500 and result.response_excerpt == "boom"
