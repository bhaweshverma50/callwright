"""Sanas noise cancellation (models ``vi`` voice isolation and ``st`` standard).

No LiveKit plugin exists (research R8), so this is a thin frame processor on the caller's input
track. The vendor streaming client is not wired yet (no vendor key or SDK available in wave 1):
frames pass through unchanged and processed audio is counted, so metering and the pipeline shape
are final and only ``_process`` changes when the client lands.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from worker.adapters.registry import VendorSpec

MODELS = {"vi": "voice_isolation", "st": "standard"}


def build(spec: VendorSpec, creds: Mapping[str, str]) -> Any:
    from livekit import rtc

    class SanasNoiseFilter(rtc.FrameProcessor[rtc.AudioFrame]):
        def __init__(self, mode: str, api_key: str) -> None:
            self.mode = mode
            self.api_key = api_key
            self.processed_ms = 0.0
            self._enabled = True

        @property
        def enabled(self) -> bool:
            return self._enabled

        @enabled.setter
        def enabled(self, value: bool) -> None:
            self._enabled = value

        def _process(self, frame: rtc.AudioFrame) -> rtc.AudioFrame:
            self.processed_ms += frame.duration * 1000.0
            return frame

        def _close(self) -> None:
            self._enabled = False

    return SanasNoiseFilter(MODELS[spec.model or "vi"], creds.get("api_key", ""))
