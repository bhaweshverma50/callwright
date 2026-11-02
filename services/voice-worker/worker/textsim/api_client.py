"""Internal API client for text simulations (008 T014; contracts simulator.yaml, test_runs.yaml).

All endpoints use ``Authorization: Bearer <service token>`` under ``CALLWRIGHT_INTERNAL_API_URL``:

- ``GET  /test-runs/{trn}/cases/{tc}/spec`` -> :class:`CaseSpec`
- ``POST /test-runs/{trn}/cases/{tc}/result`` (204)
- ``GET  /simulation-runs/{srun}/spec`` -> :class:`SimulationSpec` (marks the run running)
- ``POST /simulation-runs/{srun}/result`` (204)
- ``POST /calls/{call_id}/events`` (003, inherited from :class:`InternalApiClient`)

A spec answered with 404 or 409 means the run was cancelled or is gone: the getters return
None and the job stops without posting a result. Transport errors and 5xx are retried with
the same backoff as the live worker's posts.
"""

from __future__ import annotations

from typing import Any, Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from worker import telemetry
from worker.internal_api import (
    RETRYABLE_STATUS,
    InternalApiClient,
    InternalApiError,
    _problem_detail,
)

GONE = frozenset({404, 409})


class PersonaBrief(BaseModel):
    model_config = ConfigDict(extra="allow")

    goal: str = ""
    known_facts: list[str] = Field(default_factory=list)
    temperament: str | None = None
    speaking_style: str | None = None
    constraints: list[str] = Field(default_factory=list)
    opening_line: str | None = None


class SimSettings(BaseModel):
    model_config = ConfigDict(extra="ignore")

    max_caller_turns: int = 20
    missing_mock_policy: Literal["synthesize", "error"] = "synthesize"
    persona_model: str | None = None


class RecordedOutput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str
    output: str


def _string_map(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {str(k): "" if v is None else str(v) for k, v in value.items()}


class CaseSpec(BaseModel):
    """One single-turn test case (``internalGetTestCaseSpec``)."""

    model_config = ConfigDict(extra="ignore")

    workspace_id: str
    agent_id: str
    agent_type: Literal["single_prompt", "flow"] = "single_prompt"
    config_snapshot: dict[str, Any]
    user_prompt: str
    dynamic_variables: dict[str, str] = Field(default_factory=dict)

    @field_validator("dynamic_variables", mode="before")
    @classmethod
    def _vars(cls, value: Any) -> dict[str, str]:
        return _string_map(value)


class SimulationSpec(BaseModel):
    """One simulation run (``internalGetSimulationSpec``)."""

    model_config = ConfigDict(extra="ignore")

    workspace_id: str
    simulation_run_id: str
    output_call_id: str
    agent_id: str
    agent_type: Literal["single_prompt", "flow"] = "single_prompt"
    channel: Literal["web", "sip_inbound", "sip_outbound", "whatsapp"] = "web"
    mode: Literal["replay", "persona"]
    config_snapshot: dict[str, Any]
    settings: SimSettings = Field(default_factory=SimSettings)
    dynamic_variables: dict[str, str] = Field(default_factory=dict)
    start_speaker: Literal["agent", "user"] | None = None
    # Strings; the worker also accepts ``{"text", "interrupted"}`` items (replay_caller).
    caller_turns: list[Any] = Field(default_factory=list)
    recorded_tool_outputs: list[RecordedOutput] = Field(default_factory=list)
    original_node_path: list[str] = Field(default_factory=list)
    persona_brief: PersonaBrief | None = None

    @field_validator("dynamic_variables", mode="before")
    @classmethod
    def _vars(cls, value: Any) -> dict[str, str]:
        return _string_map(value)

    @field_validator("settings", mode="before")
    @classmethod
    def _settings(cls, value: Any) -> Any:
        return value if value is not None else {}


class TextsimApiClient(InternalApiClient):
    async def _get(self, path: str, span: Any = None) -> httpx.Response:
        last_error = ""
        for attempt in range(1, self._max_attempts + 1):
            if span is not None:
                span.set_attribute("internal_api.attempts", attempt)
            try:
                response = await self._http.get(f"{self._base}{path}", headers=self._headers)
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

    async def _spec(self, path: str, route: str) -> dict[str, Any] | None:
        attrs = {"http.request.method": "GET", "url.path": f"/v1/internal{route}"}
        with telemetry.span("internal_api.textsim_spec", attrs) as span:
            response = await self._get(path, span)
            if response.status_code in GONE:
                return None
            if response.status_code != 200:
                raise InternalApiError(response.status_code, _problem_detail(response))
            body: dict[str, Any] = response.json()
            return body

    async def _result(self, path: str, route: str, body: dict[str, Any]) -> bool:
        """Post a result. False when the run is gone (404 or 409)."""
        attrs = {"http.request.method": "POST", "url.path": f"/v1/internal{route}"}
        with telemetry.span("internal_api.textsim_result", attrs) as span:
            response = await self._post(path, body, span)
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

    async def post_case_result(
        self, test_run_id: str, test_case_id: str, body: dict[str, Any]
    ) -> bool:
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

    async def post_simulation_result(self, simulation_run_id: str, body: dict[str, Any]) -> bool:
        return await self._result(
            f"/simulation-runs/{simulation_run_id}/result",
            "/simulation-runs/{simulation_run_id}/result",
            body,
        )
