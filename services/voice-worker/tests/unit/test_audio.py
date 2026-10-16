"""T065: background audio resolution, download cache and gain."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from worker.audio import (
    BackgroundAudioCache,
    BackgroundAudioSpec,
    apply_gain,
    build_player,
    clamp_gain,
    resolve_background_audio,
    scale_frame,
)


def bg(**raw: Any) -> dict[str, Any]:
    return {"advanced": {"background_audio": raw}}


def test_disabled_or_missing() -> None:
    assert resolve_background_audio({}, None) == (None, [])
    assert resolve_background_audio(bg(enabled=False), None) == (None, [])


def test_builtin_clip_and_gain_clamp() -> None:
    spec, warnings = resolve_background_audio(
        bg(enabled=True, source={"kind": "builtin", "id": "hold_music"}, volume=3), None
    )
    assert warnings == [] and spec == BackgroundAudioSpec("builtin", "hold_music", 2.0)
    assert clamp_gain(-1) == 0.0 and clamp_gain(0.8) == 0.8


def test_unknown_clip_and_missing_url_warn() -> None:
    spec, warnings = resolve_background_audio(
        bg(enabled=True, source={"kind": "builtin", "id": "jungle"}), None
    )
    assert spec is None and warnings[0].code == "background_audio_unavailable"
    spec, warnings = resolve_background_audio(
        bg(enabled=True, source={"kind": "upload", "key": "k.mp3"}), None
    )
    assert spec is None and warnings[0].code == "background_audio_unavailable"
    spec, _ = resolve_background_audio(
        bg(enabled=True, source={"kind": "upload", "key": "k.mp3"}), "https://signed/k.mp3"
    )
    assert spec is not None and spec.url == "https://signed/k.mp3"


class Resp:
    def __init__(self, status: int, content: bytes) -> None:
        self.status_code = status
        self.content = content


class Http:
    def __init__(self, resp: Resp) -> None:
        self.resp = resp
        self.calls = 0

    async def get(self, url: str) -> Resp:
        self.calls += 1
        return self.resp


async def test_upload_download_is_cached_by_key(tmp_path: Path) -> None:
    cache = BackgroundAudioCache(tmp_path)
    spec = BackgroundAudioSpec("upload", "ws/ambient/cafe.mp3", 0.8, "https://signed")
    http = Http(Resp(200, b"ID3data"))
    first = await cache.fetch(spec, http)
    second = await cache.fetch(spec, http)
    assert first == second and first is not None and first.suffix == ".mp3"
    assert http.calls == 1
    assert await cache.fetch(spec, Http(Resp(200, b""))) == first  # cached copy reused
    other = BackgroundAudioSpec("upload", "ws/ambient/other.mp3", 0.8, "https://signed")
    assert await BackgroundAudioCache(tmp_path).fetch(other, Http(Resp(403, b""))) is None


async def test_build_player_for_builtin_clip() -> None:
    player = build_player(BackgroundAudioSpec("builtin", "office_ambience", 0.8))
    assert type(player).__name__ == "BackgroundAudioPlayer"


def test_gain_clips_and_scales_frames() -> None:
    samples = np.array([1000, -20000, 30000], dtype=np.int16)
    assert list(apply_gain(samples, 2.0)) == [2000, -32768, 32767]
    assert apply_gain(samples, 1.0) is samples
    from livekit import rtc

    frame = rtc.AudioFrame(samples.tobytes(), 16000, 1, 3)
    out = scale_frame(frame, 0.5)
    assert list(np.frombuffer(bytes(out.data), dtype=np.int16)) == [500, -10000, 15000]
