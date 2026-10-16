"""The worker's adapter catalog, read by admission (003 research R8, R22).

``services/voice-worker/worker/adapters/catalog.json`` lists every ``(kind, provider, models)``
the worker can build. The API reads the same file (no worker import), so a vendor the worker
cannot run is refused before a room exists, and Auto speech recognition (``stt.model = null``)
resolves to the same model the worker would meter (FR-045).
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class CatalogEntry:
    kind: str
    provider: str
    models: tuple[str, ...]
    aliases: tuple[str, ...] = ()
    supports_auto: bool = False
    auto_default: str | None = None
    auto_by_language: Mapping[str, str] = field(default_factory=dict)
    default_model: str | None = None


@dataclass(frozen=True)
class AdapterCatalog:
    entries: tuple[CatalogEntry, ...]

    def entry(self, kind: str, provider: str) -> CatalogEntry | None:
        for e in self.entries:
            if e.kind == kind and (e.provider == provider or provider in e.aliases):
                return e
        return None

    def canonical_provider(self, kind: str, provider: str) -> str:
        e = self.entry(kind, provider)
        return e.provider if e is not None else provider

    def supports(self, kind: str, provider: str, model: str | None) -> bool:
        e = self.entry(kind, provider)
        if e is None:
            return False
        if model is None:
            return kind != "stt" or e.supports_auto or bool(e.default_model)
        return model in e.models

    def resolve_auto_stt(self, provider: str, language: str) -> str | None:
        """Model Auto picks for ``language``: exact code, then its base (``en-US`` -> ``en``)."""
        e = self.entry("stt", provider)
        if e is None or not e.supports_auto:
            return None
        lang = (language or "").strip()
        base = lang.split("-", 1)[0].lower()
        for candidate in (lang, lang.lower(), base):
            if candidate in e.auto_by_language:
                return e.auto_by_language[candidate]
        return e.auto_default


def _entry(raw: Mapping[str, Any]) -> CatalogEntry:
    rule = raw.get("auto_rule") or {}
    return CatalogEntry(
        kind=str(raw["kind"]),
        provider=str(raw["provider"]),
        models=tuple(str(m) for m in raw.get("models", [])),
        aliases=tuple(str(a) for a in raw.get("aliases", [])),
        supports_auto=bool(raw.get("supports_auto", False)),
        auto_default=rule.get("default"),
        auto_by_language={str(k): str(v) for k, v in (rule.get("by_language") or {}).items()},
        default_model=raw.get("default_model"),
    )


def parse_catalog(data: Mapping[str, Any]) -> AdapterCatalog:
    return AdapterCatalog(tuple(_entry(e) for e in data.get("entries", [])))


@lru_cache(maxsize=4)
def load_catalog(path: Path) -> AdapterCatalog:
    return parse_catalog(json.loads(path.read_text(encoding="utf-8")))
