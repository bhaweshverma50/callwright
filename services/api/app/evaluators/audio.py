"""Recording reader and silence finder for ``audio_silence`` (007 T081, research R12, FR-040).

``decode_levels`` decodes a recording with PyAV to 16 kHz per channel and returns RMS levels in
dB for 20 ms frames, one row per party (a stereo egress gives two rows; two audio streams give
one row each; mono gives one mixed row). ``find_silences`` marks a frame silent when every row
is below ``average_db + threshold_db`` (threshold negative, relative to the call's own average
level), keeps runs of at least ``min_silence_ms`` and drops the leading run before the first
sound and the trailing run after the last.

``fetch_recording`` downloads the object through 003's signer (a short-lived GET URL), so the jobs
worker needs no storage credentials of its own.
"""

from __future__ import annotations

import io
from dataclasses import dataclass

import httpx
import numpy as np
import numpy.typing as npt

from app.evaluators.base import RecordingRef

FRAME_MS = 20
SAMPLE_RATE = 16_000
FRAME_SAMPLES = SAMPLE_RATE * FRAME_MS // 1000
FLOOR_DB = -100.0
MAX_BYTES = 200 * 1024 * 1024


class RecordingUnavailable(Exception):
    pass


@dataclass(frozen=True)
class Silence:
    start_ms: int
    duration_ms: int


def frame_levels(samples: npt.NDArray[np.float64]) -> npt.NDArray[np.float64]:
    """RMS level in dBFS of each full 20 ms frame of one channel of 16 kHz float samples."""
    frames = len(samples) // FRAME_SAMPLES
    if frames == 0:
        return np.zeros(0)
    block = samples[: frames * FRAME_SAMPLES].reshape(frames, FRAME_SAMPLES)
    rms = np.sqrt(np.mean(np.square(block), axis=1))
    with np.errstate(divide="ignore"):
        db = 20.0 * np.log10(np.maximum(rms, 1e-10))
    return np.maximum(db, FLOOR_DB)


def decode_levels(data: bytes) -> npt.NDArray[np.float64]:
    """Frame levels with shape ``(parties, frames)``."""
    import av

    channels: list[list[npt.NDArray[np.float64]]] = []
    try:
        with av.open(io.BytesIO(data), mode="r") as container:
            streams = list(container.streams.audio)
            if not streams:
                raise RecordingUnavailable("the recording has no audio")
            per_stream: dict[int, list[npt.NDArray[np.float64]]] = {}
            resamplers = {
                s.index: av.AudioResampler(
                    format="fltp", layout="stereo" if s.channels >= 2 else "mono", rate=SAMPLE_RATE
                )
                for s in streams
            }
            for packet in container.demux(*streams):
                index = packet.stream.index
                for frame in packet.decode():
                    for out in resamplers[index].resample(frame):  # type: ignore[arg-type]
                        per_stream.setdefault(index, []).append(out.to_ndarray().astype(np.float64))
            for s in streams:
                chunks = per_stream.get(s.index)
                if not chunks:
                    continue
                joined = np.concatenate(chunks, axis=1)
                channels.extend([[row] for row in joined])
    except RecordingUnavailable:
        raise
    except Exception as exc:  # PyAV raises its own error tree for corrupt or unknown media
        raise RecordingUnavailable(f"the recording could not be decoded: {exc}") from exc
    if not channels:
        raise RecordingUnavailable("the recording has no audio")
    levels = [frame_levels(c[0]) for c in channels]
    width = min(len(row) for row in levels)
    return np.vstack([row[:width] for row in levels])


def find_silences(
    levels: npt.NDArray[np.float64], *, threshold_db: float, min_silence_ms: int, frame_ms: int = FRAME_MS
) -> list[Silence]:
    """Silent stretches of at least ``min_silence_ms`` between the first and last sound."""
    if levels.ndim == 1:
        levels = levels.reshape(1, -1)
    if levels.shape[1] == 0:
        return []
    voiced = levels[levels > FLOOR_DB + 1]
    average = float(np.mean(voiced)) if voiced.size else FLOOR_DB
    cutoff = average + threshold_db
    silent = np.all(levels < cutoff, axis=0)
    sound = np.flatnonzero(~silent)
    if sound.size == 0:
        return []
    first, last = int(sound[0]), int(sound[-1])
    out: list[Silence] = []
    run_start: int | None = None
    for i in range(first, last + 2):
        is_silent = i <= last and bool(silent[i])
        if is_silent and run_start is None:
            run_start = i
        elif not is_silent and run_start is not None:
            duration = (i - run_start) * frame_ms
            if duration >= min_silence_ms:
                out.append(Silence(run_start * frame_ms, duration))
            run_start = None
    return out


async def fetch_recording(ref: RecordingRef, *, timeout_s: float = 30.0) -> bytes:
    from app.calls.ports import registry

    if registry.signer is None or not ref.bucket:
        raise RecordingUnavailable("recording storage is not configured")
    url = registry.signer.presign_get(ref.bucket, ref.key, 300)
    async with httpx.AsyncClient(timeout=timeout_s) as client:
        response = await client.get(url)
    if response.status_code != 200:
        raise RecordingUnavailable(f"the recording could not be read (HTTP {response.status_code})")
    if len(response.content) > MAX_BYTES:
        raise RecordingUnavailable("the recording is too large to analyse")
    return response.content


async def read_levels(ref: RecordingRef) -> npt.NDArray[np.float64]:
    import asyncio

    data = await fetch_recording(ref)
    return await asyncio.to_thread(decode_levels, data)
