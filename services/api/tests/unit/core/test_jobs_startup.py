"""The standalone jobs worker registers the agent versions port the post-call pipeline reads.

Regression: only ``create_app`` registered it, so on the VM worker every pipeline run failed at
``price_and_charge`` with "agent version ... is not available" and calls were never priced.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.agent_versions.runtime_port import AgentVersionsAdapter
from app.calls import ports
from app.core import jobs


async def test_startup_registers_agent_versions(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ports.registry, "agent_versions", ports.NoAgentVersions())
    ctx: dict[str, Any] = {"redis": object()}
    await jobs.startup(ctx)
    try:
        assert isinstance(ports.registry.agent_versions, AgentVersionsAdapter)
    finally:
        await jobs.shutdown(ctx)
