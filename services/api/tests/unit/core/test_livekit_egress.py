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
        self.requests: list[Any] = []

    async def start_room_composite_egress(self, request: Any) -> Any:
        self.requests.append(request)
        if self.behaviour == "hang":
            await asyncio.sleep(30)
        if self.behaviour == "refuse":
            raise RuntimeError("twirp error unavailable: no egress servers available")
        return SimpleNamespace(egress_id="EG_1")


def client(behaviour: str, **settings: Any) -> LiveKitClient:
    lk = LiveKitClient(_settings(**settings))
    egress = Egress(behaviour)
    lk._client = lambda: SimpleNamespace(egress=egress)  # type: ignore[method-assign]
    lk.egress = egress  # type: ignore[attr-defined]
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


async def test_gcp_credentials_upload_natively_to_gcs() -> None:
    lk = client("ok", recordings_gcp_credentials='{"type": "service_account"}')
    await lk.start_audio_recording("call-room", TARGET)
    out = lk.egress.requests[0].file_outputs[0]  # type: ignore[attr-defined]
    assert out.WhichOneof("output") == "gcp"
    assert out.gcp.bucket == "callwright-recordings"
    assert out.gcp.credentials == '{"type": "service_account"}'
    assert out.filepath == "recordings/ws/call.mp4"


async def test_s3_upload_falls_back_to_the_object_store_key_and_endpoint() -> None:
    lk = client(
        "ok",
        s3_access_key_id="AK",
        s3_secret_access_key="SK",
        s3_endpoint_url="https://storage.googleapis.com",
    )
    await lk.start_audio_recording("call-room", TARGET)
    s3 = lk.egress.requests[0].file_outputs[0].s3  # type: ignore[attr-defined]
    assert (s3.access_key, s3.secret) == ("AK", "SK")
    assert (s3.endpoint, s3.force_path_style) == ("https://storage.googleapis.com", True)
