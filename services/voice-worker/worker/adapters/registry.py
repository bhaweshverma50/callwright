"""Vendor adapter registry (Principle I, research R8).

Every STT, LLM, TTS and noise-cancellation vendor is one module under
``worker/adapters/<kind>/<provider>.py`` exposing ``build(spec, creds)`` and listed in
``catalog.json``. The registry maps ``(kind, provider)`` to that module, validates models against
the catalog and raises :class:`UnsupportedVendor` for anything else. Tests and the offline
harness swap builders with :meth:`AdapterRegistry.with_builders` so no vendor code runs.
"""

from __future__ import annotations

import importlib
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

Kind = Literal["stt", "llm", "tts", "nc"]
KINDS: tuple[Kind, ...] = ("stt", "llm", "tts", "nc")

CATALOG_PATH = Path(__file__).with_name("catalog.json")

Builder = Callable[["VendorSpec", Mapping[str, str]], Any]


class UnsupportedVendor(Exception):
    """A provider or model that is not in the catalog."""

    def __init__(self, kind: str, provider: str, model: str | None = None) -> None:
        self.kind = kind
        self.provider = provider
        self.model = model
        what = f"{kind}/{provider}" + (f" model {model}" if model else "")
        super().__init__(f"unsupported vendor {what}")

    @property
    def diagnostic(self) -> str:
        """Machine code stored on the call (003 data-model section 1)."""
        return f"unsupported_vendor:{self.kind}/{self.provider}"


class VendorNotConfigured(UnsupportedVendor):
    """A catalog vendor this deployment holds no key for (raised by ``build``).

    Same diagnostic as :class:`UnsupportedVendor`: for this deployment the vendor does not exist.
    """

    def __init__(self, kind: str, provider: str) -> None:
        super().__init__(kind, provider)
        self.args = (f"{kind}/{provider} has no API key on this deployment",)


class UnsupportedLanguage(Exception):
    """An Auto STT choice with no model for the language (FR-045 edge case)."""

    def __init__(self, provider: str, language: str) -> None:
        self.provider = provider
        self.language = language
        super().__init__(f"stt/{provider} Auto has no model for language {language}")


@dataclass(frozen=True)
class VendorSpec:
    """One resolved vendor choice: kind, provider, model and provider-specific options."""

    kind: Kind
    provider: str
    model: str | None
    options: Mapping[str, Any] = field(default_factory=dict)

    @property
    def key(self) -> str:
        return f"{self.kind}/{self.provider}/{self.model or ''}"


@dataclass(frozen=True)
class CatalogEntry:
    kind: Kind
    provider: str
    models: tuple[str, ...]
    aliases: tuple[str, ...] = ()
    supports_auto: bool = False
    auto_rule: Mapping[str, Any] | None = None
    builtin_turn_detection: frozenset[str] = frozenset()
    default_model: str | None = None
    capabilities: Mapping[str, bool] = field(default_factory=dict)
    streaming: bool = True
    meter: str = "none"
    internal: bool = False


@lru_cache(maxsize=4)
def load_catalog(path: Path = CATALOG_PATH) -> tuple[CatalogEntry, ...]:
    raw = json.loads(path.read_text())
    entries: list[CatalogEntry] = []
    for e in raw["entries"]:
        entries.append(
            CatalogEntry(
                kind=e["kind"],
                provider=e["provider"],
                models=tuple(e["models"]),
                aliases=tuple(e.get("aliases", ())),
                supports_auto=bool(e.get("supports_auto", False)),
                auto_rule=e.get("auto_rule"),
                builtin_turn_detection=frozenset(e.get("builtin_turn_detection", ())),
                default_model=e.get("default_model"),
                capabilities=e.get("capabilities", {}),
                streaming=bool(e.get("streaming", True)),
                meter=e.get("meter", "none"),
                internal=bool(e.get("internal", False)),
            )
        )
    return tuple(entries)


def _module_path(kind: Kind, provider: str) -> str:
    return f"worker.adapters.{kind}.{provider}"


def _import_builder(kind: Kind, provider: str) -> Builder:
    module = importlib.import_module(_module_path(kind, provider))
    build: Builder = module.build
    return build


class AdapterRegistry:
    """Maps ``(kind, provider)`` to an adapter and validates against the catalog."""

    def __init__(
        self,
        catalog: tuple[CatalogEntry, ...] | None = None,
        builders: Mapping[tuple[Kind, str], Builder] | None = None,
        default_builder: Builder | None = None,
    ) -> None:
        self._entries: dict[tuple[str, str], CatalogEntry] = {}
        self._aliases: dict[tuple[str, str], str] = {}
        for entry in catalog if catalog is not None else load_catalog():
            self._entries[(entry.kind, entry.provider)] = entry
            for alias in entry.aliases:
                self._aliases[(entry.kind, alias)] = entry.provider
        self._builders: dict[tuple[Kind, str], Builder] = dict(builders or {})
        self._default_builder = default_builder

    # catalog -------------------------------------------------------------

    def entries(self, kind: Kind | None = None) -> list[CatalogEntry]:
        return [e for e in self._entries.values() if kind is None or e.kind == kind]

    def normalize_provider(self, kind: Kind, provider: str) -> str:
        return self._aliases.get((kind, provider), provider)

    def entry(self, kind: Kind, provider: str) -> CatalogEntry:
        provider = self.normalize_provider(kind, provider)
        try:
            return self._entries[(kind, provider)]
        except KeyError:
            raise UnsupportedVendor(kind, provider) from None

    def check(self, spec: VendorSpec) -> VendorSpec:
        """Validate a spec and return it with the canonical provider id."""
        entry = self.entry(spec.kind, spec.provider)
        if spec.model is not None and spec.model not in entry.models:
            raise UnsupportedVendor(spec.kind, entry.provider, spec.model)
        if spec.provider != entry.provider:
            return VendorSpec(spec.kind, entry.provider, spec.model, spec.options)
        return spec

    def builtin_turn_detection(self, spec: VendorSpec) -> bool:
        if spec.kind != "stt" or spec.model is None:
            return False
        return spec.model in self.entry("stt", spec.provider).builtin_turn_detection

    def resolve_auto_stt(self, provider: str, language: str) -> str:
        """Fallback for Auto STT when the claim did not carry ``stt_resolved_model``.

        The API resolves Auto at claim with 002's ``resolve_auto_stt`` (FR-045); this applies the
        same catalog rule so the harness and older claims behave identically.
        """
        entry = self.entry("stt", provider)
        rule = entry.auto_rule or {}
        by_language: Mapping[str, str] = rule.get("by_language", {})
        lang = language.lower()
        candidates = [lang, lang.split("-")[0]]
        for candidate in candidates:
            if candidate in by_language:
                return by_language[candidate]
        default = rule.get("default")
        if default is None:
            raise UnsupportedLanguage(entry.provider, language)
        return str(default)

    # building ------------------------------------------------------------

    def with_builders(
        self,
        builders: Mapping[tuple[Kind, str], Builder] | None = None,
        default_builder: Builder | None = None,
    ) -> AdapterRegistry:
        """Return a copy whose builders are replaced (fakes in tests and the harness)."""
        clone = AdapterRegistry(tuple(self._entries.values()))
        clone._builders = {**self._builders, **(builders or {})}
        clone._default_builder = default_builder or self._default_builder
        return clone

    def build(self, spec: VendorSpec, creds: Mapping[str, str]) -> Any:
        spec = self.check(spec)
        key = (spec.kind, spec.provider)
        builder = self._builders.get(key)
        if builder is None:
            builder = self._default_builder or _import_builder(spec.kind, spec.provider)
        return builder(spec, creds)


def has_module(kind: Kind, provider: str) -> bool:
    """True when the adapter module for ``(kind, provider)`` exists in the package."""
    return Path(__file__).with_name(kind).joinpath(f"{provider}.py").exists()
