"""The vendors the voice worker can run (``adapters.json``): the worker's adapter registry builds
from it and the API's admission refuses anything else (003 research R8, R22). It also owns what
the worker needs to know per model (built-in end of turn, native volume, fixed temperature) and
the built-in background sounds the worker can play."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from functools import lru_cache
from importlib import resources
from typing import Any, Literal

Kind = Literal["stt", "llm", "tts", "nc"]


@dataclass(frozen=True)
class AdapterEntry:
    kind: Kind
    provider: str
    models: tuple[str, ...]
    aliases: tuple[str, ...] = ()
    default_model: str | None = None
    builtin_turn_detection: frozenset[str] = frozenset()
    native_volume: frozenset[str] = frozenset()
    fixed_temperature: frozenset[str] = frozenset()


@dataclass(frozen=True)
class AdapterCatalog:
    entries: tuple[AdapterEntry, ...]
    # Built-in background sound id -> LiveKit ``BuiltinAudioClip`` name.
    ambience_clips: Mapping[str, str] = field(default_factory=dict)

    def entry(self, kind: str, provider: str) -> AdapterEntry | None:
        return next(
            (e for e in self.entries if e.kind == kind and (e.provider == provider or provider in e.aliases)),
            None,
        )

    def canonical_provider(self, kind: str, provider: str) -> str:
        e = self.entry(kind, provider)
        return e.provider if e is not None else provider

    def supports(self, kind: str, provider: str, model: str | None) -> bool:
        e = self.entry(kind, provider)
        return e is not None and (model is None or model in e.models)


def parse_catalog(data: Mapping[str, Any]) -> AdapterCatalog:
    return AdapterCatalog(
        tuple(
            AdapterEntry(
                kind=e["kind"],
                provider=str(e["provider"]),
                models=tuple(str(m) for m in e.get("models", ())),
                aliases=tuple(str(a) for a in e.get("aliases", ())),
                default_model=e.get("default_model"),
                builtin_turn_detection=frozenset(e.get("builtin_turn_detection", ())),
                native_volume=frozenset(e.get("native_volume", ())),
                fixed_temperature=frozenset(e.get("fixed_temperature", ())),
            )
            for e in data.get("entries", ())
        ),
        {str(k): str(v) for k, v in (data.get("ambience_clips") or {}).items()},
    )


@lru_cache(maxsize=1)
def load_catalog() -> AdapterCatalog:
    text = resources.files("callwright_contract").joinpath("adapters.json").read_text(encoding="utf-8")
    return parse_catalog(json.loads(text))
