"""Vendor adapter registry (Principle I, research R8).

Every STT, LLM, TTS and noise-cancellation vendor is one module under
``worker/adapters/<kind>/<provider>.py`` exposing ``build(spec, creds)`` and listed in the
contract's adapter catalog (``callwright_contract/adapters.json``). The registry maps
``(kind, provider)`` to that module, validates models against the catalog and raises
:class:`UnsupportedVendor` for anything else. Tests and the offline harness swap builders with
:meth:`AdapterRegistry.with_builders` so no vendor code runs.
"""

from __future__ import annotations

import importlib
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from callwright_contract.adapters import AdapterCatalog, AdapterEntry, Kind, load_catalog

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
    """Speech recognition Auto has no model for the language (FR-045 edge case)."""

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

    @property
    def required_model(self) -> str:
        """The model the claim resolved; a spec without one cannot be built."""
        if self.model is None:
            raise UnsupportedVendor(self.kind, self.provider)
        return self.model


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
        catalog: AdapterCatalog | None = None,
        builders: Mapping[tuple[Kind, str], Builder] | None = None,
        default_builder: Builder | None = None,
    ) -> None:
        self._entries: dict[tuple[str, str], AdapterEntry] = {}
        self._aliases: dict[tuple[str, str], str] = {}
        for entry in (catalog or load_catalog()).entries:
            self._entries[(entry.kind, entry.provider)] = entry
            for alias in entry.aliases:
                self._aliases[(entry.kind, alias)] = entry.provider
        self._builders: dict[tuple[Kind, str], Builder] = dict(builders or {})
        self._default_builder = default_builder

    # catalog -------------------------------------------------------------

    def entries(self, kind: Kind | None = None) -> list[AdapterEntry]:
        return [e for e in self._entries.values() if kind is None or e.kind == kind]

    def normalize_provider(self, kind: Kind, provider: str) -> str:
        return self._aliases.get((kind, provider), provider)

    def entry(self, kind: Kind, provider: str) -> AdapterEntry:
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

    # building ------------------------------------------------------------

    def with_builders(
        self,
        builders: Mapping[tuple[Kind, str], Builder] | None = None,
        default_builder: Builder | None = None,
    ) -> AdapterRegistry:
        """Return a copy whose builders are replaced (fakes in tests and the harness)."""
        clone = AdapterRegistry(AdapterCatalog(tuple(self._entries.values())))
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
