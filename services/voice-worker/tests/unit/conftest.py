from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from callwright_contract.protocol import RuntimeConfig

from tests.harness.runner import build_runtime, deep_merge, load_agent_config


@pytest.fixture
def agent_config() -> dict[str, Any]:
    return load_agent_config()


def make_runtime(overrides: dict[str, Any] | None = None, **runtime: Any) -> RuntimeConfig:
    config = deep_merge(load_agent_config(), overrides or {})
    return build_runtime(config, runtime)


@pytest.fixture
def no_llm_prewarm(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """AgentSession prewarms the LLM connection; tests must stay offline."""
    from livekit.agents import llm

    monkeypatch.setattr(llm.LLM, "prewarm", lambda self, **_: None)
    yield
