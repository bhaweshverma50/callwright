"""The worker's health listener (Cloud Run needs one): 200 while the loop runs, 503 after."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import httpx

from app.core.worker_health import is_healthy, serve_health


@dataclass
class FakeWorker:
    main_task: asyncio.Task[None] | None = None


async def _get(port: int) -> httpx.Response:
    async with httpx.AsyncClient() as client:
        return await client.get(f"http://127.0.0.1:{port}/healthz")


async def test_health_reports_the_worker_loop() -> None:
    worker = FakeWorker()
    assert not is_healthy(worker)
    stop = asyncio.Event()
    worker.main_task = asyncio.create_task(stop.wait())  # type: ignore[assignment]
    server = await serve_health(worker, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    try:
        ok = await _get(port)
        assert ok.status_code == 200
        assert ok.json() == {"status": "ok", "role": "worker"}

        stop.set()
        await worker.main_task
        stopped = await _get(port)
        assert stopped.status_code == 503
        assert stopped.json()["status"] == "stopped"
    finally:
        server.close()
        await server.wait_closed()
