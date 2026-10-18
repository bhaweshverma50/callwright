"""Egress start against a media server without an egress service: bounded, and a LiveKitError."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from app.core.config import Settings
from app.core.livekit import EgressTarget, LiveKitClient, LiveKitError


def _settings(**values: Any) -> Settings:
    return Settings(_env_file=None, **values)  # type: ignore[call-arg]


class Egress:
    def __init__(self, behaviour: str) -> None:
        self.behaviour = behaviour

    async def start_room_composite_egress(self, request: Any) -> Any:
        if self.behaviour == "hang":
            await asyncio.sleep(30)
        if self.behaviour == "refuse":
            raise RuntimeError("twirp error unavailable: no egress servers available")
        return SimpleNamespace(egress_id="EG_1")


def client(behaviour: str, **settings: Any) -> LiveKitClient:
    lk = LiveKitClient(_settings(**settings))
    lk._client = lambda: SimpleNamespace(egress=Egress(behaviour))  # type: ignore[method-assign]
    return lk


TARGET = EgressTarget(bucket="callwright-recordings", key="recordings/ws/call.mp4")


async def test_a_hanging_egress_request_times_out_as_livekit_error() -> None:
    lk = client("hang", recordings_egress_timeout_s=0.05)
    with pytest.raises(LiveKitError, match=r"no egress service answered within 0\.05 s"):
        await lk.start_audio_recording("call-room", TARGET)


async def test_a_refused_egress_request_is_a_livekit_error() -> None:
    with pytest.raises(LiveKitError, match="no egress servers available"):
        await client("refuse").start_audio_recording("call-room", TARGET)


async def test_a_started_egress_returns_its_id() -> None:
    assert await client("ok").start_audio_recording("call-room", TARGET) == "EG_1"


def test_recordings_are_enabled_by_default_and_switchable(monkeypatch: pytest.MonkeyPatch) -> None:
    assert _settings().recordings_enabled is True
    monkeypatch.setenv("RECORDINGS_ENABLED", "false")
    assert _settings().recordings_enabled is False
