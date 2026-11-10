"""003 T069: the Anthropic adapter, offline (no key and no network)."""

from __future__ import annotations

import json
from typing import Any

import pytest

from worker.adapters.llm import anthropic as adapter
from worker.adapters.registry import (
    AdapterRegistry,
    UnsupportedVendor,
    VendorNotConfigured,
    VendorSpec,
)
from worker.settings import WorkerSettings
from worker.textsim.llm import default_factory

HAIKU = VendorSpec("llm", "anthropic", "claude-haiku-5-5", {"temperature": 0.4})
SONNET = VendorSpec("llm", "anthropic", "claude-sonnet-5-5")


SSE = (
    b"event: message_start\n"
    b'data: {"type":"message_start","message":{"id":"m","type":"message","role":"assistant",'
    b'"model":"x","content":[],"stop_reason":null,"usage":{"input_tokens":1,"output_tokens":1}}}'
    b'\n\nevent: message_stop\ndata: {"type":"message_stop"}\n\n'
)


@pytest.fixture
def wire(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """The JSON bodies the plugin sends over HTTP; the transport answers with an empty stream."""
    import httpx2

    bodies: list[dict[str, Any]] = []

    async def handle(self: Any, request: httpx2.Request) -> httpx2.Response:
        bodies.append(json.loads(request.content))
        return httpx2.Response(
            200, headers={"content-type": "text/event-stream"}, content=SSE, request=request
        )

    monkeypatch.setattr(httpx2.AsyncHTTPTransport, "handle_async_request", handle)
    return bodies


async def request_body(llm: Any, wire: list[dict[str, Any]]) -> dict[str, Any]:
    """The request body sent for one user turn after an assistant turn."""
    from livekit.agents.llm import ChatContext

    ctx = ChatContext()
    ctx.add_message(role="system", content="You are a receptionist.")
    ctx.add_message(role="user", content="Hi")
    ctx.add_message(role="assistant", content="Hello, how can I help?")
    async with llm.chat(chat_ctx=ctx) as stream:
        async for _ in stream:
            pass
    (body,) = wire
    return body


def test_registry_selects_the_anthropic_adapter() -> None:
    registry = AdapterRegistry()
    entry = registry.entry("llm", "anthropic")
    assert entry.models == ("claude-haiku-5-5", "claude-sonnet-5-5")
    built = registry.build(HAIKU, {"api_key": "test-key"})
    assert type(built).__module__ == adapter.__name__
    assert built.model == "claude-haiku-5-5"
    with pytest.raises(UnsupportedVendor):
        registry.check(VendorSpec("llm", "anthropic", "claude-3-opus-20240229"))


def test_no_key_means_not_configured() -> None:
    with pytest.raises(VendorNotConfigured) as exc:
        AdapterRegistry().build(HAIKU, {"api_key": ""})
    assert exc.value.diagnostic == "unsupported_vendor:llm/anthropic"
    assert isinstance(exc.value, UnsupportedVendor)


def test_settings_carry_the_key() -> None:
    assert WorkerSettings.model_validate({"ANTHROPIC_API_KEY": ""}).vendor_credentials()[
        "anthropic"
    ] == {"api_key": ""}
    creds = WorkerSettings.model_validate({"ANTHROPIC_API_KEY": "sk-ant"}).vendor_credentials()
    assert creds["anthropic"] == {"api_key": "sk-ant"}


async def test_haiku_request_has_thinking_off_and_no_sampling(wire: list[dict[str, Any]]) -> None:
    llm = adapter.build(HAIKU, {"api_key": "test-key"})
    body = await request_body(llm, wire)
    assert body["model"] == "claude-haiku-5-5"
    assert body["max_tokens"] == adapter.MAX_TOKENS
    assert body["thinking"] == {"type": "disabled"}
    assert "temperature" not in body
    # No prefill: the request ends on a user turn.
    assert body["messages"][-1]["role"] == "user"


async def test_sonnet_request_turns_thinking_off_between_tools(wire: list[dict[str, Any]]) -> None:
    body = await request_body(adapter.build(SONNET, {"api_key": "test-key"}), wire)
    assert body["thinking"] == {"type": "between_tools"}
    assert body["messages"][-1]["role"] == "user"


def test_claude_models_take_no_temperature() -> None:
    registry = AdapterRegistry()
    assert registry.fixed_temperature(VendorSpec("llm", "anthropic", "claude-haiku-5-5"))
    assert not registry.fixed_temperature(VendorSpec("llm", "anthropic", None))


def test_text_simulations_use_offline_scripts_without_a_key() -> None:
    factory = default_factory(AdapterRegistry(), {"anthropic": {"api_key": ""}})
    model = factory(HAIKU, "agent", None)
    assert type(model).__module__.startswith("worker.textsim")
