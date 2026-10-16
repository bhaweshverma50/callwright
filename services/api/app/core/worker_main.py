"""arq jobs worker with a minimal HTTP health endpoint, for hosts that need a listener.

Cloud Run only accepts a service that listens on ``$PORT``, so ``python -m app.core.worker_main``
runs the same worker as ``arq app.core.jobs.WorkerSettings`` and also answers any HTTP request
on ``$PORT`` (default 8080) with 200 while the worker loop runs and 503 once it has stopped.
SIGTERM and SIGINT stop the worker the way the arq CLI does. When the worker loop dies with an
error the process exits non-zero so the platform restarts the container.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
from typing import Protocol

logger = logging.getLogger("app.worker")

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


async def run(port: int) -> None:
    from arq.worker import create_worker

    from app.core.config import get_settings
    from app.core.jobs import WorkerSettings
    from app.core.logging import configure_logging

    settings = get_settings()
    configure_logging(settings.log_level, settings.log_json)
    # Registers SIGINT/SIGTERM handlers on this loop, like the arq CLI.
    worker = create_worker(WorkerSettings)  # type: ignore[arg-type]
    server = await serve_health(worker, "0.0.0.0", port)  # noqa: S104 (container listener)
    logger.info("worker health endpoint listening on :%s", port)
    try:
        await worker.async_run()
    except asyncio.CancelledError:
        logger.info("worker stopped")
    finally:
        server.close()
        await server.wait_closed()
        await worker.close()


def main() -> None:
    asyncio.run(run(int(os.environ.get("PORT", "8080"))))


if __name__ == "__main__":
    main()
