"""Minimal HTTP health endpoint for the arq jobs worker (``app.worker``), for hosts that need a
listener: Cloud Run only accepts a service that listens on ``$PORT``. Any HTTP request gets 200
while the worker loop runs and 503 once it has stopped.
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import Protocol

_REQUEST_TIMEOUT_S = 5.0


class _Running(Protocol):
    main_task: asyncio.Task[None] | None


def is_healthy(worker: _Running) -> bool:
    task = worker.main_task
    return task is not None and not task.done()


def _response(status: str, body: bytes) -> bytes:
    head = (
        f"HTTP/1.1 {status}\r\n"
        "Content-Type: application/json\r\n"
        f"Content-Length: {len(body)}\r\n"
        "Cache-Control: no-store\r\n"
        "Connection: close\r\n\r\n"
    )
    return head.encode("ascii") + body


async def serve_health(worker: _Running, host: str, port: int) -> asyncio.Server:
    """Answer every HTTP request with the worker's liveness (200 ok, 503 stopped)."""

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            with contextlib.suppress(asyncio.TimeoutError, asyncio.IncompleteReadError, ConnectionError):
                await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), _REQUEST_TIMEOUT_S)
            if is_healthy(worker):
                writer.write(_response("200 OK", b'{"status":"ok","role":"worker"}'))
            else:
                writer.write(_response("503 Service Unavailable", b'{"status":"stopped","role":"worker"}'))
            with contextlib.suppress(ConnectionError):
                await writer.drain()
        finally:
            writer.close()
            with contextlib.suppress(ConnectionError):
                await writer.wait_closed()

    return await asyncio.start_server(handle, host, port)
