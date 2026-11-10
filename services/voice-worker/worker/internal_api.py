"""The worker's client for every internal API route (``/v1/internal/*``, research R19).

All routes authenticate with ``Authorization: Bearer <service token>``. Every body is
a contract model (``callwright_contract.protocol`` and, for the text runner, ``.textsim``).

Retried with exponential backoff (transport errors, 408, 425, 429 and 5xx; every route is
idempotent or deduplicated server side):

- ``POST /calls/claim`` with :class:`ClaimRequest` returns :class:`ClaimResponse`; 404 or 409
  raise :class:`ClaimRejected`.
- ``POST /calls/{call_id}/events`` with ``{"events": [...]}`` (up to ``MAX_EVENTS_PER_BATCH``;
  empty is a pure heartbeat) returns :class:`EventBatchResult`. ``control.action == "end_call"``
  orders the worker to hang up (mid-call credit guard, FR-025). Duplicate ``seq`` values are
  ignored server side; 409 means the call is terminal (:class:`CallClosed`).
- Text runs (008): ``GET /test-runs/{trn}/cases/{tc}/spec`` (:class:`CaseSpec`),
  ``GET /simulation-runs/{srun}/spec`` (:class:`SimulationSpec`) and their ``POST .../result``.
  404 or 409 mean the run was cancelled or is gone.

Asked once while a call waits on the answer (the caller hears the delay, so no retries):

- ``GET /calls/{call_id}/tool-secrets`` (005): the call's secret header values.
- ``POST /knowledge/search`` (005 ``kb_search``).
- ``POST /calls/{call_id}/callbacks`` (011 ``schedule_callback``).
- ``POST /calls/{call_id}/language`` (012 ``set_language``, in the background).
"""

from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import Awaitable, Callable, Sequence
from typing import Any

import httpx
from callwright_contract.protocol import (
    MAX_EVENTS_PER_BATCH,
    CallbackRequest,
    ClaimRequest,
    ClaimResponse,
    EventBatchResult,
    KbSearchRequest,
    LanguageReport,
    ToolSecrets,
)
from callwright_contract.textsim import CaseResult, CaseSpec, SimResult, SimulationSpec
from pydantic import BaseModel, ValidationError

from worker import telemetry
from worker.settings import WorkerSettings

log = logging.getLogger(__name__)


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
GONE = frozenset({404, 409})

Sleep = Callable[[float], Awaitable[None]]


class InternalApiClient:
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

    @classmethod
    def from_settings(cls, settings: WorkerSettings) -> InternalApiClient:
        return cls(
            settings.internal_api_url,
            settings.service_token.get_secret_value(),
            timeout_s=settings.http_timeout_s,
            max_attempts=settings.events_max_attempts,
            backoff_base_s=settings.events_backoff_base_s,
        )

    async def aclose(self) -> None:
        if self._owns_http:
            await self._http.aclose()

    def backoff_delay(self, attempt: int) -> float:
        """Delay before retry ``attempt`` (1-based): base * 2^(attempt-1), capped, +-10% jitter."""
        delay = min(self._backoff_max, self._backoff_base * (2 ** (attempt - 1)))
        return float(delay * random.uniform(0.9, 1.1))

    async def _once(
        self, method: str, path: str, body: Any = None, timeout_s: float | None = None
    ) -> httpx.Response:
        options: dict[str, Any] = {} if timeout_s is None else {"timeout": timeout_s}
        return await self._http.request(
            method, f"{self._base}{path}", json=body, headers=self._headers, **options
        )

    async def _retried(
        self, method: str, path: str, body: Any = None, span: Any = None
    ) -> httpx.Response:
        last_error = ""
        for attempt in range(1, self._max_attempts + 1):
            if span is not None:
                span.set_attribute("internal_api.attempts", attempt)
            try:
                response = await self._once(method, path, body)
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
            response = await self._retried(
                "POST", "/calls/claim", request.model_dump(exclude_none=True), span
            )
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
            response = await self._retried(
                "POST", f"/calls/{call_id}/events", {"events": list(events)}, span
            )
            if response.status_code == 409:
                raise CallClosed(409, _problem_detail(response))
            if response.status_code != 200:
                raise InternalApiError(response.status_code, _problem_detail(response))
            result = EventBatchResult.model_validate(response.json())
            span.set_attribute("control.action", result.control.action)
            return result

    async def tool_secrets(self, call_id: str) -> dict[str, str]:
        """The call's secret map, or an empty map when the API cannot provide it (tools then
        answer ``secret_unavailable`` and the call goes on). Values are never logged."""
        try:
            response = await self._once("GET", f"/calls/{call_id}/tool-secrets")
        except httpx.HTTPError as exc:
            log.warning("tool secrets unavailable for %s: %s", call_id, type(exc).__name__)
            return {}
        if response.status_code != 200:
            log.warning("tool secrets unavailable for %s: HTTP %s", call_id, response.status_code)
            return {}
        try:
            return ToolSecrets.model_validate(response.json()).secrets
        except (ValueError, ValidationError):
            log.warning("tool secrets unreadable for %s", call_id)
            return {}

    async def kb_search(self, body: KbSearchRequest, *, timeout_s: float) -> dict[str, Any]:
        """Search results, or ``{}`` when the API fails. Raises ``TimeoutError`` after
        ``timeout_s``."""
        try:
            response = await asyncio.wait_for(
                self._once("POST", "/knowledge/search", _json(body, sparse=True)), timeout_s
            )
            data = response.json() if response.status_code == 200 else {}
        except httpx.TimeoutException as exc:
            raise TimeoutError from exc
        except (httpx.HTTPError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    async def schedule_callback(
        self, call_id: str, body: CallbackRequest, *, timeout_s: float
    ) -> tuple[int, Any]:
        """The status and JSON answer of a booking. Raises :class:`InternalApiError` when the
        API cannot be reached or answers no JSON."""
        try:
            response = await self._once(
                "POST", f"/calls/{call_id}/callbacks", _json(body, sparse=True), timeout_s
            )
            return response.status_code, response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise InternalApiError(None, type(exc).__name__) from exc

    async def report_language(
        self, call_id: str, body: LanguageReport, *, timeout_s: float
    ) -> None:
        try:
            response = await self._once(
                "POST", f"/calls/{call_id}/language", _json(body, sparse=True), timeout_s
            )
        except httpx.HTTPError as exc:
            log.warning("language report for %s failed: %s", call_id, exc)
            return
        if response.status_code != 200:
            log.warning("language report for %s: HTTP %s", call_id, response.status_code)

    async def _spec(self, path: str, route: str) -> dict[str, Any] | None:
        attrs = {"http.request.method": "GET", "url.path": f"/v1/internal{route}"}
        with telemetry.span("internal_api.textsim_spec", attrs) as span:
            response = await self._retried("GET", path, span=span)
            if response.status_code in GONE:
                return None
            if response.status_code != 200:
                raise InternalApiError(response.status_code, _problem_detail(response))
            body: dict[str, Any] = response.json()
            return body

    async def _result(self, path: str, route: str, body: BaseModel) -> bool:
        """Post a result. False when the run is gone (404 or 409)."""
        attrs = {"http.request.method": "POST", "url.path": f"/v1/internal{route}"}
        with telemetry.span("internal_api.textsim_result", attrs) as span:
            response = await self._retried("POST", path, _json(body), span)
            if response.status_code in GONE:
                return False
            if response.status_code not in (200, 202, 204):
                raise InternalApiError(response.status_code, _problem_detail(response))
            return True

    async def case_spec(self, test_run_id: str, test_case_id: str) -> CaseSpec | None:
        raw = await self._spec(
            f"/test-runs/{test_run_id}/cases/{test_case_id}/spec",
            "/test-runs/{test_run_id}/cases/{test_case_id}/spec",
        )
        return CaseSpec.model_validate(raw) if raw is not None else None

    async def post_case_result(self, test_run_id: str, test_case_id: str, body: CaseResult) -> bool:
        return await self._result(
            f"/test-runs/{test_run_id}/cases/{test_case_id}/result",
            "/test-runs/{test_run_id}/cases/{test_case_id}/result",
            body,
        )

    async def simulation_spec(self, simulation_run_id: str) -> SimulationSpec | None:
        raw = await self._spec(
            f"/simulation-runs/{simulation_run_id}/spec",
            "/simulation-runs/{simulation_run_id}/spec",
        )
        return SimulationSpec.model_validate(raw) if raw is not None else None

    async def post_simulation_result(self, simulation_run_id: str, body: SimResult) -> bool:
        return await self._result(
            f"/simulation-runs/{simulation_run_id}/result",
            "/simulation-runs/{simulation_run_id}/result",
            body,
        )


def _json(body: BaseModel, *, sparse: bool = False) -> dict[str, Any]:
    """The body as JSON; ``sparse`` leaves out unset optional fields (tool requests)."""
    return body.model_dump(mode="json", exclude_none=sparse)


def _problem_detail(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return response.text[:500]
    if isinstance(body, dict):
        return str(body.get("detail") or body.get("title") or body)
    return str(body)
