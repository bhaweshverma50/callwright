"""Typed client for the API's internal worker endpoints (``/v1/internal/*``).

Shapes are the contract's (``callwright_contract.protocol``). Both endpoints authenticate with
``Authorization: Bearer <service token>`` (research R19).

- ``POST {base}/calls/claim`` with :class:`ClaimRequest` returns :class:`ClaimResponse`.
  Idempotent per ``job_id``, so transport failures and 5xx are retried.
- ``POST {base}/calls/{call_id}/events`` with ``{"events": [...]}`` (up to
  ``MAX_EVENTS_PER_BATCH`` items; empty is a pure heartbeat) returns :class:`EventBatchResult`.
  ``control.action == "end_call"`` orders the worker to hang up with ``control.disconnect_reason``
  (mid-call credit guard, FR-025).
  Duplicate ``seq`` values are ignored server side, so every retry is safe. 409 means the call is
  already terminal: the worker stops posting (:class:`CallClosed`).
"""

from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable, Sequence
from typing import Any

import httpx
from callwright_contract.protocol import (
    MAX_EVENTS_PER_BATCH,
    ClaimRequest,
    ClaimResponse,
    EventBatchResult,
)

from worker import telemetry


class InternalApiError(Exception):
    def __init__(self, status_code: int | None, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"internal API error {status_code}: {detail}")


class ClaimRejected(InternalApiError):
    """404 unknown call or 409 claimed by another job or already terminal."""


class CallClosed(InternalApiError):
    """409 on events: the call is terminal or processing; stop posting."""


RETRYABLE_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})

Sleep = Callable[[float], Awaitable[None]]


class InternalApiClient:
    """Async client with retry and exponential backoff for the two internal endpoints."""

    def __init__(
        self,
        base_url: str,
        service_token: str,
        *,
        http: httpx.AsyncClient | None = None,
        timeout_s: float = 5.0,
        max_attempts: int = 5,
        backoff_base_s: float = 0.5,
        backoff_max_s: float = 8.0,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        self._base = base_url.rstrip("/")
        self._headers = {"Authorization": f"Bearer {service_token}"}
        self._http = http or httpx.AsyncClient(timeout=timeout_s)
        self._owns_http = http is None
        self._max_attempts = max(1, max_attempts)
        self._backoff_base = backoff_base_s
        self._backoff_max = backoff_max_s
        self._sleep = sleep

    async def aclose(self) -> None:
        if self._owns_http:
            await self._http.aclose()

    def backoff_delay(self, attempt: int) -> float:
        """Delay before retry ``attempt`` (1-based): base * 2^(attempt-1), capped, +-10% jitter."""
        delay = min(self._backoff_max, self._backoff_base * (2 ** (attempt - 1)))
        return float(delay * random.uniform(0.9, 1.1))

    async def _post(self, path: str, body: dict[str, Any], span: Any = None) -> httpx.Response:
        last_error: str = ""
        for attempt in range(1, self._max_attempts + 1):
            if span is not None:
                span.set_attribute("internal_api.attempts", attempt)
            try:
                response = await self._http.post(
                    f"{self._base}{path}", json=body, headers=self._headers
                )
            except httpx.TransportError as exc:
                last_error = f"{type(exc).__name__}: {exc}"
            else:
                if span is not None:
                    span.set_attribute("http.response.status_code", response.status_code)
                if response.status_code not in RETRYABLE_STATUS:
                    return response
                last_error = f"HTTP {response.status_code}"
            if attempt < self._max_attempts:
                await self._sleep(self.backoff_delay(attempt))
        raise InternalApiError(None, f"gave up after {self._max_attempts} attempts: {last_error}")

    async def claim(self, request: ClaimRequest) -> ClaimResponse:
        attrs = {
            "http.request.method": "POST",
            "url.path": "/v1/internal/calls/claim",
            "livekit.job_id": request.job_id,
            "livekit.room": request.room_name,
        }
        with telemetry.span("internal_api.claim", attrs) as span:
            response = await self._post("/calls/claim", request.model_dump(exclude_none=True), span)
            if response.status_code in (404, 409):
                raise ClaimRejected(response.status_code, _problem_detail(response))
            if response.status_code != 200:
                raise InternalApiError(response.status_code, _problem_detail(response))
            result = ClaimResponse.model_validate(response.json())
            span.set_attribute("claim.admitted", result.admitted)
            span.set_attribute("call_id", result.call_id)
            return result

    async def post_events(self, call_id: str, events: Sequence[dict[str, Any]]) -> EventBatchResult:
        if len(events) > MAX_EVENTS_PER_BATCH:
            raise ValueError(f"at most {MAX_EVENTS_PER_BATCH} events per batch")
        seqs = [e["seq"] for e in events if isinstance(e.get("seq"), int)]
        attrs = {
            "http.request.method": "POST",
            "url.path": "/v1/internal/calls/{call_id}/events",
            "call_id": call_id,
            "events.count": len(events),
            "events.first_seq": min(seqs) if seqs else None,
            "events.last_seq": max(seqs) if seqs else None,
        }
        with telemetry.span("internal_api.events", attrs) as span:
            response = await self._post(f"/calls/{call_id}/events", {"events": list(events)}, span)
            if response.status_code == 409:
                raise CallClosed(409, _problem_detail(response))
            if response.status_code != 200:
                raise InternalApiError(response.status_code, _problem_detail(response))
            result = EventBatchResult.model_validate(response.json())
            span.set_attribute("control.action", result.control.action)
            return result


def _problem_detail(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return response.text[:500]
    if isinstance(body, dict):
        return str(body.get("detail") or body.get("title") or body)
    return str(body)
