"""Speech-like WAV fixtures for the live benchmark, made without TTS or recordings.

A small source-filter (formant) synthesizer: a glottal pulse train with natural pitch drift and
jitter, filtered through three vowel formant resonators per syllable, syllable amplitude
envelopes, fricative noise bursts between some syllables and short pauses between words. The
result has speech's energy rhythm and spectrum closely enough for Silero VAD to treat it as
voice, which is all the benchmark needs (the fake STT returns the scripted text).

Deterministic: the same text and seed give the same samples. Regenerate the committed fixtures
with ``python -m tests.harness.bench.synth``.
"""

from __future__ import annotations

import argparse
import random
import wave
from collections.abc import Sequence
from pathlib import Path

import numpy as np
import numpy.typing as npt
import yaml

SAMPLE_RATE = 16000
FIXTURES_DIR = Path(__file__).parent / "fixtures"
CALLSET = Path(__file__).parent / "callset.yaml"

# (F1, F2, F3) in Hz for a few vowels.
VOWELS = {
    "a": (730, 1090, 2440),
    "e": (530, 1840, 2480),
    "i": (390, 1990, 2550),
    "o": (570, 840, 2410),
    "u": (440, 1020, 2240),
}

Signal = npt.NDArray[np.float64]


def _resonator(x: Signal, freq: float, bandwidth: float, rate: int) -> Signal:
    """Two-pole resonator (Klatt style), unity gain at DC."""
    r = np.exp(-np.pi * bandwidth / rate)
    c = -(r**2)
    b = 2 * r * np.cos(2 * np.pi * freq / rate)
    a = 1 - b - c
    y = np.zeros_like(x)
    y1 = y2 = 0.0
    for n in range(len(x)):
        y0 = a * x[n] + b * y1 + c * y2
        y[n] = y0
        y2, y1 = y1, y0
    return y


def _syllable(rng: random.Random, f0: float, duration_s: float, rate: int) -> Signal:
    n = int(duration_s * rate)
    t = np.arange(n) / rate
    # Pitch: slow drift plus 1% jitter, as a glottal pulse train.
    pitch = f0 * (1 + 0.08 * np.sin(2 * np.pi * rng.uniform(1.5, 3.0) * t + rng.uniform(0, 6)))
    pitch *= 1 + np.array([rng.gauss(0, 0.01) for _ in range(n)])
    phase = np.cumsum(pitch / rate)
    pulses = np.diff(np.floor(phase), prepend=0.0)
    source = np.convolve(pulses, np.exp(-np.arange(int(0.004 * rate)) / (0.0008 * rate)))[:n]
    source += np.array([rng.gauss(0, 0.02) for _ in range(n)])  # breathiness
    vowel = VOWELS[rng.choice(list(VOWELS))]
    out = np.zeros(n)
    for formant, bw, gain in zip(vowel, (80, 100, 150), (1.0, 0.6, 0.3), strict=True):
        out += gain * _resonator(source, formant, bw, rate)
    attack = min(n, int(0.03 * rate))
    release = min(n, int(0.06 * rate))
    env = np.ones(n)
    env[:attack] = np.linspace(0, 1, attack)
    env[n - release :] = np.linspace(1, 0, release)
    return out * env


def _fricative(rng: random.Random, duration_s: float, rate: int) -> Signal:
    n = int(duration_s * rate)
    noise = np.array([rng.gauss(0, 1) for _ in range(n)])
    hiss = _resonator(noise, rng.uniform(3500, 5500), 1200, rate)
    return hiss * np.hanning(n) * 0.25


def synthesize(text: str, *, seed: int = 0, rate: int = SAMPLE_RATE, f0: float = 120.0) -> Signal:
    """Speech-like audio for ``text`` (one syllable per vowel group), peak normalized."""
    rng = random.Random(f"{seed}:{text}")
    parts: list[Signal] = []
    for word in text.split():
        syllables = max(
            1,
            sum(
                1
                for i, ch in enumerate(word.lower())
                if ch in "aeiouy" and (i == 0 or word.lower()[i - 1] not in "aeiouy")
            ),
        )
        for _ in range(syllables):
            if rng.random() < 0.35:
                parts.append(_fricative(rng, rng.uniform(0.04, 0.08), rate))
            parts.append(_syllable(rng, f0 * rng.uniform(0.9, 1.1), rng.uniform(0.14, 0.22), rate))
        parts.append(np.zeros(int(rng.uniform(0.03, 0.07) * rate)))
    audio = np.concatenate(parts)
    peak = float(np.max(np.abs(audio))) or 1.0
    return audio / peak * 0.7


def to_pcm16(audio: Signal) -> npt.NDArray[np.int16]:
    return np.asarray(np.clip(audio, -1.0, 1.0) * 32767, dtype=np.int16)


def write_wav(path: Path, audio: Signal, rate: int = SAMPLE_RATE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(to_pcm16(audio).tobytes())


def read_wav(path: Path) -> tuple[npt.NDArray[np.int16], int]:
    with wave.open(str(path), "rb") as wav:
        if wav.getnchannels() != 1 or wav.getsampwidth() != 2:
            raise ValueError(f"{path}: expected 16-bit mono")
        return np.frombuffer(wav.readframes(wav.getnframes()), dtype=np.int16), wav.getframerate()


def fixture_name(index: int) -> str:
    return f"turn_{index + 1}.wav"


def generate(turns: Sequence[str], out_dir: Path = FIXTURES_DIR, seed: int = 0) -> list[Path]:
    paths = []
    for i, text in enumerate(turns):
        path = out_dir / fixture_name(i)
        write_wav(path, synthesize(text, seed=seed))
        paths.append(path)
    return paths


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Regenerate the live benchmark WAV fixtures")
    parser.add_argument("--callset", type=Path, default=CALLSET)
    parser.add_argument("--out", type=Path, default=FIXTURES_DIR)
    args = parser.parse_args(argv)
    callset = yaml.safe_load(args.callset.read_text())
    for path in generate(callset["turns"], args.out):
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
