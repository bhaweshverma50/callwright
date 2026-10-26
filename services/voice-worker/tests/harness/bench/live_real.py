"""Real-vendor pieces for the live benchmark (``--vendors real``).

The job runs the production ``job_entry`` with the real adapter registry, so Deepgram, OpenAI
and ElevenLabs (or whatever the call set's agent config selects) answer for real; keys come
from the worker's environment. Two bench-only additions make the slow paths measurable:

- :class:`BenchToolProvider` gives the agent one tool, ``check_availability``, that sleeps
  ``tool_delay_ms`` like a calendar or database lookup, so a caller turn that needs it shows
  the instant acknowledgement and the answer after the tool.
- :class:`SlowTurnLLM` holds back the real LLM's first token by ``slow_delay_ms`` on caller
  turns that contain ``slow_marker``, so a turn whose model is slow to start shows the
  thinking backchannel deterministically (a real model is only sometimes that slow).
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from livekit.agents import llm
from livekit.agents.types import DEFAULT_API_CONNECT_OPTIONS, APIConnectOptions

from worker.adapters.registry import AdapterRegistry, VendorSpec
from worker.turn_detection import last_user_text

AVAILABILITY_TOOL = "check_availability"


@dataclass
class RealBenchParams:
    """Carried in the dispatch metadata (``bench``) next to ``call_id``."""

    tool_delay_ms: float = 1500.0
    slow_marker: str = ""
    slow_delay_ms: float = 1500.0

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> RealBenchParams:
        return cls(
            tool_delay_ms=float(data.get("tool_delay_ms", 1500.0)),
            slow_marker=str(data.get("slow_marker") or ""),
            slow_delay_ms=float(data.get("slow_delay_ms", 1500.0)),
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "vendors": "real",
            "tool_delay_ms": self.tool_delay_ms,
            "slow_marker": self.slow_marker,
            "slow_delay_ms": self.slow_delay_ms,
        }


class BenchToolProvider:
    """One slow lookup tool for every bench call (stands in for 005's HTTP tools)."""

    def __init__(self, delay_ms: float) -> None:
        self.delay_s = delay_ms / 1000.0

    def tools_for(self, runtime: Any, control: Any) -> Sequence[Any]:
        from livekit.agents import function_tool

        delay = self.delay_s

        async def check_availability(day: str) -> str:
            """Look up free appointment slots for one day in the clinic calendar.

            Args:
                day: The day the caller asked about, for example "Friday".
            """
            await asyncio.sleep(delay)
            return f"Free slots on {day}: 10:00 am and 2:30 pm."

        return [function_tool(check_availability, name=AVAILABILITY_TOOL)]


class _DelayedStream(llm.LLMStream):
    def __init__(self, owner: SlowTurnLLM, inner: Any, delay_s: float, **kwargs: Any) -> None:
        super().__init__(owner, **kwargs)
        self._inner = inner
        self._delay_s = delay_s

    async def _run(self) -> None:
        try:
            if self._delay_s > 0:
                await asyncio.sleep(self._delay_s)
            async for chunk in self._inner:
                self._event_ch.send_nowait(chunk)
        finally:
            with contextlib.suppress(Exception):
                await self._inner.aclose()


class SlowTurnLLM(llm.LLM):  # type: ignore[type-arg]
    """The real LLM, with the first token held back on caller turns containing the marker."""

    def __init__(self, inner: Any, marker: str, delay_ms: float) -> None:
        super().__init__()
        self.inner = inner
        self.marker = marker.lower()
        self.delay_s = delay_ms / 1000.0

    @property
    def model(self) -> str:
        return str(self.inner.model)

    @property
    def provider(self) -> str:
        return str(self.inner.provider)

    async def _prewarm_impl(self) -> None:
        self.inner.prewarm()

    def chat(
        self,
        *,
        chat_ctx: Any,
        tools: list[Any] | None = None,
        conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS,
        **kwargs: Any,
    ) -> Any:
        items = list(getattr(chat_ctx, "items", []) or [])
        last = items[-1] if items else None
        caller_turn = (
            getattr(last, "type", None) == "message" and getattr(last, "role", "") == "user"
        )
        slow = bool(self.marker) and caller_turn and self.marker in last_user_text(chat_ctx).lower()
        inner = self.inner.chat(chat_ctx=chat_ctx, tools=tools, conn_options=conn_options, **kwargs)
        return _DelayedStream(
            self,
            inner,
            self.delay_s if slow else 0.0,
            chat_ctx=chat_ctx,
            tools=tools or [],
            conn_options=conn_options,
        )


def real_registry(params: RealBenchParams, base: AdapterRegistry | None = None) -> AdapterRegistry:
    """The production registry; the LLM is wrapped by :class:`SlowTurnLLM` when a marker is set."""
    registry = base or AdapterRegistry()
    if not params.slow_marker:
        return registry

    def build_llm(spec: VendorSpec, creds: Mapping[str, str]) -> Any:
        from worker.adapters.registry import _import_builder

        inner = _import_builder("llm", spec.provider)(spec, creds)
        return SlowTurnLLM(inner, params.slow_marker, params.slow_delay_ms)

    return registry.with_builders(
        {("llm", "openai"): build_llm, ("llm", "azure_openai"): build_llm}
    )
