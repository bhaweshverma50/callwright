"""Audio-side behaviour: pronunciation replacement before TTS and background ambience (R12).

Pronunciation runs as a streaming text transform in the agent's TTS node: whole-word,
case-insensitive, holding back a trailing partial word until a boundary arrives so replacements
across chunk boundaries work. The transcript is taken from the LLM output before the transform,
so it keeps the original words (FR-018).
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import AsyncIterable, AsyncIterator, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

# --------------------------------------------------------------------------------------------
# Pronunciation


@dataclass(frozen=True)
class PronunciationEntry:
    word: str
    replacement: str


def entries_from_config(raw: Iterable[Mapping[str, Any]] | None) -> list[PronunciationEntry]:
    """Read ``advanced.pronunciation[]``, dropping empty rows and case-insensitive duplicates."""
    seen: set[str] = set()
    out: list[PronunciationEntry] = []
    for row in raw or ():
        word = str(row.get("word") or "").strip()
        replacement = str(row.get("replacement") or "").strip()
        if not word or not replacement or word.lower() in seen:
            continue
        seen.add(word.lower())
        out.append(PronunciationEntry(word, replacement))
    return out


class PronunciationTransform:
    """Streaming whole-word replacer. ``feed`` returns text safe to speak; ``flush`` the rest."""

    def __init__(self, entries: Iterable[PronunciationEntry]) -> None:
        self._entries = sorted(entries, key=lambda e: len(e.word), reverse=True)
        self._by_lower = {e.word.lower(): e.replacement for e in self._entries}
        self._buffer = ""
        if self._entries:
            alternation = "|".join(re.escape(e.word) for e in self._entries)
            # Streaming: a match must be followed by a real non-word character, so "SQL" at the
            # end of a chunk waits in case the next chunk continues the word ("SQLite").
            self._streaming = re.compile(rf"(?<!\w)(?:{alternation})(?=\W)", re.IGNORECASE)
            self._final = re.compile(rf"(?<!\w)(?:{alternation})(?!\w)", re.IGNORECASE)
            self._hold_tokens = max(len(e.word.split()) for e in self._entries)
        else:
            self._streaming = self._final = re.compile(r"(?!x)x")
            self._hold_tokens = 0

    @property
    def enabled(self) -> bool:
        return bool(self._entries)

    def apply(self, text: str) -> str:
        """Replace in a complete text."""
        if not self._entries:
            return text
        return self._final.sub(lambda m: self._by_lower[m.group(0).lower()], text)

    def feed(self, chunk: str) -> str:
        if not self._entries:
            return chunk
        self._buffer += chunk
        out: list[str] = []
        pos = 0
        for match in self._streaming.finditer(self._buffer):
            out.append(self._buffer[pos : match.start()])
            out.append(self._by_lower[match.group(0).lower()])
            pos = match.end()
        tail = self._buffer[pos:]
        cut = _hold_back_start(tail, self._hold_tokens)
        out.append(tail[:cut])
        self._buffer = tail[cut:]
        return "".join(out)

    def flush(self) -> str:
        rest, self._buffer = self._buffer, ""
        return self.apply(rest)

    async def stream(self, text: AsyncIterable[str]) -> AsyncIterator[str]:
        async for chunk in text:
            out = self.feed(chunk)
            if out:
                yield out
        rest = self.flush()
        if rest:
            yield rest


def _hold_back_start(tail: str, tokens: int) -> int:
    """Index where the last ``tokens`` whitespace-separated tokens of ``tail`` begin.

    A match that is not complete yet must reach the end of the buffer, so it starts inside the
    last ``tokens`` tokens (entries span at most ``tokens`` words). Trailing whitespace counts as
    a completed token boundary.
    """
    if tokens <= 0 or not tail:
        return len(tail)
    spans = [m.start() for m in re.finditer(r"\S+", tail)]
    if not spans:
        return len(tail)
    if tail[-1].isspace():
        # The last token is complete; only multi-word entries need earlier tokens.
        keep = tokens - 1
        if keep <= 0:
            return len(tail)
        return spans[-keep] if len(spans) >= keep else 0
    return spans[-tokens] if len(spans) >= tokens else 0


# --------------------------------------------------------------------------------------------
# Background audio

BUILTIN_AMBIENCE: Mapping[str, str] = {
    "office_ambience": "OFFICE_AMBIENCE",
    "city_ambience": "CITY_AMBIENCE",
    "forest_ambience": "FOREST_AMBIENCE",
    "crowded_room": "CROWDED_ROOM",
    "hold_music": "HOLD_MUSIC",
    "keyboard_typing": "KEYBOARD_TYPING",
    "keyboard_typing2": "KEYBOARD_TYPING2",
}
MAX_GAIN = 2.0


@dataclass(frozen=True)
class BackgroundAudioSpec:
    kind: Literal["builtin", "upload"]
    ref: str  # builtin clip id or upload object key
    gain: float
    url: str | None = None


@dataclass(frozen=True)
class AudioWarning:
    code: str
    detail: str


def clamp_gain(volume: float) -> float:
    """Builder range 0..3 to player gain 0..2 (clipping guard)."""
    return round(max(0.0, min(MAX_GAIN, float(volume))), 4)


def resolve_background_audio(
    config: Mapping[str, Any], signed_url: str | None
) -> tuple[BackgroundAudioSpec | None, list[AudioWarning]]:
    """Read ``advanced.background_audio`` and the claim's signed URL into a playable spec."""
    adv: Mapping[str, Any] = config.get("advanced") or {}
    raw: Mapping[str, Any] = adv.get("background_audio") or {}
    if not raw.get("enabled"):
        return None, []
    source: Mapping[str, Any] = raw.get("source") or {}
    gain = clamp_gain(float(raw.get("volume", 0.8)))
    kind = source.get("kind")
    if kind == "builtin":
        clip = str(source.get("id") or "")
        if clip not in BUILTIN_AMBIENCE:
            return None, [AudioWarning("background_audio_unavailable", f"unknown clip {clip}")]
        return BackgroundAudioSpec("builtin", clip, gain), []
    if kind == "upload":
        key = str(source.get("key") or "")
        if not signed_url:
            return None, [AudioWarning("background_audio_unavailable", f"no signed URL for {key}")]
        return BackgroundAudioSpec("upload", key, gain, signed_url), []
    return None, [AudioWarning("background_audio_unavailable", "background audio has no source")]


class BackgroundAudioCache:
    """Downloads uploaded ambience files once per object key."""

    def __init__(self, directory: Path) -> None:
        self._dir = directory

    def path_for(self, key: str) -> Path:
        digest = hashlib.sha256(key.encode()).hexdigest()[:32]
        suffix = Path(key).suffix or ".audio"
        return self._dir / f"{digest}{suffix}"

    async def fetch(self, spec: BackgroundAudioSpec, http: Any) -> Path | None:
        """Return a local file for an upload spec, or None when it cannot be read."""
        if spec.kind != "upload" or not spec.url:
            return None
        path = self.path_for(spec.ref)
        if path.exists() and path.stat().st_size > 0:
            return path
        try:
            response = await http.get(spec.url)
        except Exception:
            return None
        if response.status_code != 200 or not response.content:
            return None
        self._dir.mkdir(parents=True, exist_ok=True)
        path.write_bytes(response.content)
        return path


def build_player(spec: BackgroundAudioSpec, local_file: Path | None = None) -> Any:
    """LiveKit ``BackgroundAudioPlayer`` playing the ambience for the whole call."""
    from livekit.agents import AudioConfig, BackgroundAudioPlayer, BuiltinAudioClip

    source: Any
    if spec.kind == "builtin":
        source = getattr(BuiltinAudioClip, BUILTIN_AMBIENCE[spec.ref])
    else:
        if local_file is None:
            raise ValueError("upload ambience needs a downloaded file")
        source = str(local_file)
    return BackgroundAudioPlayer(ambient_sound=AudioConfig(source, volume=spec.gain))


def apply_gain(samples: Any, volume: float) -> Any:
    """Scale int16 PCM samples (numpy array) by ``volume`` (0..2) with clipping."""
    import numpy as np

    if volume == 1.0:
        return samples
    scaled = samples.astype(np.float32) * float(volume)
    return np.clip(scaled, -32768, 32767).astype(np.int16)
