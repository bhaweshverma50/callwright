"""The replay CLI (``python -m app.worker replay <call_id>``, 003 quickstart section 6) runs
outside the API and the jobs worker, so it installs the features itself: without 002's agent
versions ``price_and_charge`` cannot read the call's config, and a replay of a completed call reset
its steps and then blocked on ``LookupError: agent version ... is not available``."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

import pytest

from app import worker
from app.calls import ports
from app.calls.pipeline import PipelineRun
from app.core.ids import new_id


class _Result:
    def scalar(self) -> str:
        return "ws_replay"


class _Session:
    async def execute(self, *_: Any, **__: Any) -> _Result:
        return _Result()


class _Db:
    def __init__(self, *_: Any, **__: Any) -> None:
        pass

    @asynccontextmanager
    async def transaction(self, **_: Any) -> Any:
        yield _Session()

    async def dispose(self) -> None:
        pass


class _Queue:
    async def aclose(self) -> None:
        pass


async def test_replay_registers_agent_versions(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    async def fake_run(db: Any, queue: Any, workspace_id: str, call_id: str, **kwargs: Any) -> PipelineRun:
        seen["port"] = ports.registry.agent_versions
        seen["args"] = (workspace_id, call_id, kwargs["replay"])
        return PipelineRun(status="finished")

    monkeypatch.setattr(ports.registry, "agent_versions", ports.NoAgentVersions())
    monkeypatch.setattr(worker, "Database", _Db)
    monkeypatch.setattr(worker, "run_pipeline_for", fake_run)
    monkeypatch.setattr(worker, "ArqJobQueue", _Queue)

    call_id = new_id("call")
    assert await worker.replay(call_id) == 0
    assert seen["args"] == ("ws_replay", call_id, True)
    assert not isinstance(seen["port"], ports.NoAgentVersions)
