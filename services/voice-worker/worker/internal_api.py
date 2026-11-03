"""Typed client for the API's internal worker endpoints (``/v1/internal/*``).

Shapes follow ``specs/003-voice-runtime/contracts/calls.yaml`` (claim) and
``contracts/call_events.yaml`` (events). Both endpoints authenticate with
``Authorization: Bearer <service token>`` (research R19).

- ``POST {base}/calls/claim`` with :class:`ClaimRequest` returns :class:`ClaimResponse`.
  Idempotent per ``job_id``, so transport failures and 5xx are retried.
- ``POST {base}/calls/{call_id}/events`` with ``{"events": [...]}`` (0 to 200 items; empty is a
  pure heartbeat) returns :class:`EventBatchResult`. ``control.action == "end_call"`` orders the
  worker to hang up with ``control.disconnect_reason`` (mid-call credit guard, FR-025).
  Duplicate ``seq`` values are ignored server side, so every retry is safe. 409 means the call is
  already terminal: the worker stops posting (:class:`CallClosed`).
"""

from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable, Sequence
from typing import Any, Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field

from worker import telemetry

Channel = Literal["web", "sip_inbound", "sip_outbound", "whatsapp"]
DisconnectReason = Literal[
    "user_hangup",
    "agent_hangup",
    "call_transfer",
    "voicemail_reached",
    "inactivity",
    "max_duration_reached",
    "error",
    "concurrency_limit",
    "insufficient_credit",
]

MAX_EVENTS_PER_BATCH = 200


# --------------------------------------------------------------------------------------------
# Claim


class SipAttributes(BaseModel):
    model_config = ConfigDict(extra="ignore")

    call_id: str | None = None
    trunk_id: str | None = None
    trunk_phone_number: str | None = None
    caller_number: str | None = None
    participant_identity: str | None = None


class ClaimRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str
    room_name: str
    worker_id: str
    dispatch_metadata: dict[str, Any]
    sip: SipAttributes | None = None


class Refusal(BaseModel):
    disconnect_reason: Literal["insufficient_credit", "concurrency_limit", "error"]
    diagnostic: str | None = None


class Limits(BaseModel):
    end_on_silence_s: int = 30
    max_duration_s: int = 600
    ring_duration_ms: int = 5000


class OutboundDial(BaseModel):
    sip_trunk_id: str
    to_number: str
    from_number: str
    ring_timeout_s: int = 30


class ControlRange(BaseModel):
    """One row of 002's shared control range table (data-model 8.6), used to clamp overrides."""

    model_config = ConfigDict(extra="ignore")

    path: str
    min: float
    max: float
    step: float | None = None


class LanguageOption(BaseModel):
    """One language the caller can switch to (012); the agent's own language comes first."""

    model_config = ConfigDict(extra="ignore")

    code: str
    label: str
    stt_model: str | None = None
    tts_model: str | None = None


class RuntimeConfig(BaseModel):
    """Frozen configuration for one call (contract ``RuntimeConfig``)."""

    model_config = ConfigDict(extra="allow")

    channel: Channel
    direction: Literal["inbound", "outbound"]
    from_number: str | None = None
    to_number: str | None = None
    agent_id: str
    agent_version_id: str
    agent_type: Literal["single_prompt", "flow"] = "single_prompt"
    config: dict[str, Any]
    variables: dict[str, str] = Field(default_factory=dict)
    limits: Limits = Field(default_factory=Limits)
    background_audio_url: str | None = None
    caller_join_timeout_s: int = 60
    outbound_dial: OutboundDial | None = None
    heartbeat_interval_s: int = 10
    recording_enabled: bool | None = None
    stt_resolved_model: str | None = None
    controls: list[ControlRange] | None = None
    # 012: languages set_language may switch to, and the phone caller's saved language.
    language_options: list[LanguageOption] = Field(default_factory=list)
    caller_language: str | None = None


class ClaimResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    admitted: bool
    call_id: str
    refusal: Refusal | None = None
    runtime: RuntimeConfig | None = None


# --------------------------------------------------------------------------------------------
# Events


class Control(BaseModel):
    action: Literal["none", "end_call"] = "none"
    disconnect_reason: Literal["insufficient_credit", "error"] | None = None


class EventBatchResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    accepted: int
    duplicates: int
    control: Control = Field(default_factory=Control)


# --------------------------------------------------------------------------------------------
# Errors


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
