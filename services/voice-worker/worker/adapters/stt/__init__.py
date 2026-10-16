"""Speech-to-text adapters. Each module exposes ``build(spec, creds) -> stt.STT``."""

from __future__ import annotations


def language_base(language: str) -> str:
    """``en-US`` -> ``en``; ``multi`` stays ``multi``."""
    return language.split("-")[0].lower()
