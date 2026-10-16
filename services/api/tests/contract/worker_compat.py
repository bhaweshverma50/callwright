"""Load the voice worker's own internal API client and event recorder for compatibility tests.

``services/voice-worker/worker/internal_api.py`` and ``worker/metrics.py`` need only pydantic,
httpx and OpenTelemetry, which the API environment has, so the API tests drive the real API with
the real worker code (no copied shapes). Every request and response that passes through is
validated against the assembled contract. Skipped when the worker sources are not present.
"""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from openapi_core.testing import MockRequest

from tests.contract.conftest import check, contract

WORKER_DIR = Path(__file__).resolve().parents[3] / "voice-worker"


def worker_modules() -> tuple[ModuleType, ModuleType]:
    if not (WORKER_DIR / "worker" / "internal_api.py").exists():
        pytest.skip("voice-worker sources not present")
    if str(WORKER_DIR) not in sys.path:
        sys.path.insert(0, str(WORKER_DIR))
    return importlib.import_module("worker.internal_api"), importlib.import_module("worker.metrics")


def check_request(request: httpx.Request) -> None:
    mock = MockRequest(
        "http://testserver",
        request.method.lower(),
        request.url.path,
        args=dict(request.url.params),
        headers=dict(request.headers),
        data=request.content,
        content_type=request.headers.get("content-type", "application/json").split(";")[0],
    )
    try:
        contract().validate_request(mock)
    except Exception as exc:  # pragma: no cover - failure path
        body = json.loads(request.content or b"null")
        pytest.fail(
            f"worker request {request.method} {request.url.path} breaks the contract: {exc!r} / "
            f"{exc.__cause__!r}\nbody: {json.dumps(body)[:800]}"
        )


class ContractRecorder:
    """httpx event hooks validating every worker request and API response."""

    def __init__(self) -> None:
        self.exchanges: list[tuple[httpx.Request, httpx.Response]] = []

    async def on_request(self, request: httpx.Request) -> None:
        check_request(request)

    async def on_response(self, response: httpx.Response) -> None:
        await response.aread()
        check(response)
        self.exchanges.append((response.request, response))


def worker_client(
    app: FastAPI, token: str = "dev-service-token"
) -> tuple[Any, ContractRecorder, httpx.AsyncClient]:
    """The worker's ``InternalApiClient`` wired to the ASGI app with contract hooks."""
    internal_api, _ = worker_modules()
    recorder = ContractRecorder()
    http = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
        event_hooks={"request": [recorder.on_request], "response": [recorder.on_response]},
    )

    async def no_sleep(_: float) -> None:
        return None

    client = internal_api.InternalApiClient(
        "http://testserver/v1/internal", token, http=http, max_attempts=2, sleep=no_sleep
    )
    return client, recorder, http
