"""003 T069: the Anthropic adapter, offline (no key and no network)."""

from __future__ import annotations

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


async def request_body(llm: Any) -> dict[str, Any]:
    """The keyword arguments the plugin sends to ``messages.create`` for one user turn."""
    from livekit.agents.llm import ChatContext

    sent: dict[str, Any] = {}

    async def create(**kwargs: Any) -> Any:
        sent.update(kwargs)
        return None

    llm._client.messages.create = create
    ctx = ChatContext()
    ctx.add_message(role="system", content="You are a receptionist.")
    ctx.add_message(role="user", content="Hi")
    ctx.add_message(role="assistant", content="Hello, how can I help?")
    stream = llm.chat(chat_ctx=ctx)
    await stream._create_anthropic_stream()
    await stream.aclose()
    return sent


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


async def test_haiku_request_has_thinking_off_and_no_sampling() -> None:
    llm = adapter.build(HAIKU, {"api_key": "test-key"})
    body = await request_body(llm)
    assert body["model"] == "claude-haiku-5-5"
    assert body["max_tokens"] == adapter.MAX_TOKENS
    assert body["extra_body"] == {"thinking": {"type": "disabled"}}
    assert "temperature" not in body and "temperature" not in body["extra_body"]
    # No prefill: the request ends on a user turn.
    assert body["messages"][-1]["role"] == "user"


async def test_sonnet_request_turns_thinking_off_between_tools() -> None:
    body = await request_body(adapter.build(SONNET, {"api_key": "test-key"}))
    assert body["extra_body"] == {"thinking": {"type": "between_tools"}}
    assert body["messages"][-1]["role"] == "user"


def test_claude_models_take_no_temperature() -> None:
    registry = AdapterRegistry()
    assert registry.fixed_temperature(VendorSpec("llm", "anthropic", "claude-haiku-5-5"))
    assert not registry.fixed_temperature(VendorSpec("llm", "anthropic", None))


def test_text_simulations_use_offline_scripts_without_a_key() -> None:
    factory = default_factory(AdapterRegistry(), {"anthropic": {"api_key": ""}})
    model = factory(HAIKU, "agent", None)
    assert type(model).__module__.startswith("worker.textsim")
