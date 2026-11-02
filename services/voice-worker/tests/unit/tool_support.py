"""Fakes for 005 tool tests: a call backend, tool specs and a ``CallTools`` builder."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import httpx

from tests.unit.conftest import make_runtime
from worker.control import RuntimeCallControl
from worker.metrics import EventRecorder
from worker.tools.registry import CallTools, build_call_tools


class Backend:
    def __init__(self) -> None:
        self.ended: list[str] = []
        self.said: list[str] = []
        self.tones: list[str] = []

    async def speak(self, text: str, allow_interruptions: bool) -> None:
        self.said.append(text)

    async def end(self, reason: str, diagnostic: str | None) -> None:
        self.ended.append(reason)

    async def send_dtmf(self, digits: str) -> None:
        self.tones.append(digits)


@dataclass
class Harness:
    tools: CallTools
    backend: Backend
    recorder: EventRecorder
    requests: list[httpx.Request] = field(default_factory=list)

    def events(self) -> list[dict[str, Any]]:
        return [e for e in self.recorder.history if e["type"] == "tool_call"]


def tool(
    type_: str, name: str, config: dict[str, Any] | None = None, **extra: Any
) -> dict[str, Any]:
    return {
        "tool_id": f"tool_{name}",
        "type": type_,
        "name": name,
        "description": f"{name} tool",
        "config": config or {},
        **extra,
    }


def http_spec(name: str = "check_availability", **config: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "method": "POST",
        "url": "https://api.example.com/slots",
        "headers": [],
        "body_template": None,
        "timeout_ms": 2000,
        "response_mappings": [],
        "speak_during_execution": True,
        "execution_message": "One moment while I check that.",
        "parameters": {
            "type": "object",
            "properties": {"date": {"type": "string"}},
            "required": ["date"],
        },
    }
    return tool("http", name, {**base, **config})


async def public_resolver(host: str, port: int) -> list[str]:
    return ["93.184.216.34"]


def make(
    tools: list[dict[str, Any]],
    *,
    channel: str = "sip_inbound",
    simulation: bool = False,
    handler: Callable[[httpx.Request], Any] | None = None,
    secrets: dict[str, str] | None = None,
    knowledge: list[dict[str, Any]] | None = None,
    api_handler: Callable[[httpx.Request], Any] | None = None,
    **kwargs: Any,
) -> Harness:
    overrides: dict[str, Any] = {"tools": tools}
    if knowledge is not None:
        overrides["knowledge"] = knowledge
        overrides["kb_ids"] = [k["kb_id"] for k in knowledge]
    runtime = make_runtime(overrides, channel=channel)
    if simulation:
        runtime = runtime.model_copy(update={"simulation": True})
    recorder = EventRecorder()
    backend = Backend()
    control = RuntimeCallControl("call_test", recorder, backend)
    seen: list[httpx.Request] = []

    def record(request: httpx.Request) -> Any:
        seen.append(request)
        if handler is None:
            return httpx.Response(200, json={"ok": True})
        return handler(request)

    http = httpx.AsyncClient(transport=httpx.MockTransport(record))
    api = httpx.AsyncClient(transport=httpx.MockTransport(api_handler or record))
    built = build_call_tools(
        runtime,
        control,
        tool_secrets=secrets,
        http_client=http,
        api_client=api,
        api_base_url="http://api.test/v1/internal",
        service_token="svc",
        resolver=public_resolver,
        **kwargs,
    )
    built.clients += [http, api]
    return Harness(built, backend, recorder, seen)
