"""Text-to-speech adapters. Each module exposes ``build(spec, creds) -> tts.TTS``.

Spec options carry the AgentConfig voice settings: ``voice_id``, ``speed`` (0.5..2),
``expressiveness`` (0..2), ``volume`` (0..2) and ``language``. Volume is applied by the worker as
output gain (``worker.audio.apply_gain``) for vendors without a native volume control.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def opt_float(options: Mapping[str, Any], key: str, default: float) -> float:
    value = options.get(key)
    return default if value is None else float(value)


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))
