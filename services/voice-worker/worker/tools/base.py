"""Tool executor types (005 T011).

* :class:`ToolSpecView`: one entry of the version snapshot's ``tools`` list (data-model ToolSpec),
  or the system ``kb_search`` tool.
* :class:`ToolContext`: what an executor may use on the call: the call control, the channel, the
  simulation flag (with 008's optional answerer for HTTP tools and webhook nodes), the variable
  store (dynamic variables plus values mapped by earlier tools), the per-call secret map and a
  ``say`` that speaks without touching the LLM context.
* :class:`ToolResult`: what the LLM receives (``llm_payload``) and what the ``tool_call`` event
  records.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

from callwright_contract import http_core
from callwright_contract.calls import PHONE_CHANNELS

from worker.tools import CallControl

Say = Callable[[str], Awaitable[None]]


@dataclass(frozen=True)
class ToolSpecView:
    tool_id: str | None
    type: str
    name: str
    description: str
    config: Mapping[str, Any] = field(default_factory=dict)
    mock_response: str | None = None

    @classmethod
    def from_snapshot(cls, raw: Mapping[str, Any]) -> ToolSpecView:
        return cls(
            tool_id=raw.get("tool_id"),
            type=str(raw.get("type") or ""),
            name=str(raw.get("name") or ""),
            description=str(raw.get("description") or ""),
            config=dict(raw.get("config") or {}),
            mock_response=raw.get("mock_response"),
        )


SimulatedAnswer = Callable[
    ["ToolSpecView", Mapping[str, Any], "ToolContext"], Awaitable["ToolResult"]
]
"""008 text simulations: answers an HTTP tool or webhook node instead of its canned response
(mock, recorded output, synthesized stand-in or error; ``worker.textsim.mock_tools``)."""


@dataclass
class ToolContext:
    control: CallControl
    channel: str
    simulation: bool = False
    simulated_answer: SimulatedAnswer | None = None
    dynamic_variables: dict[str, Any] = field(default_factory=dict)
    mapped_variables: dict[str, Any] = field(default_factory=dict)
    secrets: dict[str, str] = field(default_factory=dict)
    say: Say | None = None
    # Waits until the reply that called the tool has finished playing (LiveKit RunContext).
    wait_for_playout: Callable[[], Awaitable[None]] | None = None
    # True when this reply already spoke (text or a filler) before the tool ran.
    reply_spoke: Callable[[], bool] = lambda: False
    turn_index: Callable[[], int | None] = lambda: None
    # 012: replace the reply-language line in the running agent's instructions.
    set_reply_language: Callable[[str], Awaitable[None]] | None = None

    @property
    def call_id(self) -> str:
        return self.control.call_id

    @property
    def is_sip(self) -> bool:
        return self.channel in PHONE_CHANNELS

    async def speak(self, text: str) -> None:
        if self.say is not None:
            await self.say(text)
        else:
            await self.control.say(text)


@dataclass
class ToolResult:
    llm_payload: str
    is_error: bool = False
    error_code: str | None = None
    output: str | None = None
    mocked: bool = False
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def error(cls, code: str, message: str, **extra: Any) -> ToolResult:
        payload = http_core.error_payload(code, message, extra.get("http_status"))
        return cls(llm_payload=payload, is_error=True, error_code=code, extra=extra)


class ToolExecutor(Protocol):
    async def execute(
        self, spec: ToolSpecView, arguments: Mapping[str, Any], ctx: ToolContext
    ) -> ToolResult: ...
