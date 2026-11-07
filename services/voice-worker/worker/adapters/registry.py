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
from dataclasses import dataclass, field, replace
from typing import Any

from callwright_contract import diagnostics as diag
from callwright_contract.adapters import AdapterCatalog, AdapterEntry, Kind, load_catalog

Builder = Callable[["VendorSpec", Mapping[str, str]], Any]


class UnsupportedVendor(Exception):
    """A provider or model that is not in the catalog."""

    def __init__(self, kind: Kind, provider: str, model: str | None = None) -> None:
        self.kind = kind
        self.provider = provider
        self.model = model
        what = f"{kind}/{provider}" + (f" model {model}" if model else "")
        super().__init__(f"unsupported vendor {what}")

    @property
    def diagnostic(self) -> str:
        """Machine code stored on the call (contract ``diagnostics``)."""
        return diag.diagnostic(diag.UNSUPPORTED_VENDOR, self.kind, self.provider, self.model)


class VendorNotConfigured(UnsupportedVendor):
    """A catalog vendor this deployment holds no key for (raised by ``build``).

    Same diagnostic as :class:`UnsupportedVendor`: for this deployment the vendor does not exist.
    """

    def __init__(self, kind: Kind, provider: str) -> None:
        super().__init__(kind, provider)
        self.args = (f"{kind}/{provider} has no API key on this deployment",)


class UnsupportedLanguage(Exception):
    """Speech recognition Auto has no model for the language (FR-045 edge case)."""

    def __init__(self, provider: str, language: str) -> None:
        self.provider = provider
        self.language = language
        super().__init__(f"stt/{provider} Auto has no model for language {language}")

    @property
    def diagnostic(self) -> str:
        return diag.diagnostic(diag.STT_LANGUAGE_UNSUPPORTED, self.provider, self.language)


@dataclass(frozen=True)
class VendorSpec:
    """One resolved vendor choice: kind, provider, model and provider-specific options.
    :meth:`AdapterRegistry.check` attaches the catalog ``entry``, so an adapter reads the
    model's capabilities from it."""

    kind: Kind
    provider: str
    model: str | None
    options: Mapping[str, Any] = field(default_factory=dict)
    entry: AdapterEntry | None = field(default=None, compare=False, repr=False)

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
        self.catalog = catalog or load_catalog()
        self._builders: dict[tuple[Kind, str], Builder] = dict(builders or {})
        self._default_builder = default_builder

    def normalize_provider(self, kind: Kind, provider: str) -> str:
        return self.catalog.canonical_provider(kind, provider)

    def entry(self, kind: Kind, provider: str) -> AdapterEntry:
        found = self.catalog.entry(kind, provider)
        if found is None:
            raise UnsupportedVendor(kind, provider)
        return found

    def check(self, spec: VendorSpec) -> VendorSpec:
        """Validate a spec and return it with the canonical provider id and its catalog entry."""
        entry = self.entry(spec.kind, spec.provider)
        if spec.model is not None and spec.model not in entry.models:
            raise UnsupportedVendor(spec.kind, entry.provider, spec.model)
        return replace(spec, provider=entry.provider, entry=entry)

    def native_volume(self, spec: VendorSpec) -> bool:
        """Whether the TTS vendor applies ``volume`` itself; otherwise the worker applies it as
        output gain."""
        return spec.model in self.entry(spec.kind, spec.provider).native_volume

    def fixed_temperature(self, spec: VendorSpec) -> bool:
        """Whether the model only runs at the vendor's default temperature (callers that want
        another one, such as 008's simulated caller, leave it unset)."""
        entry = self.catalog.entry(spec.kind, spec.provider)
        return entry is not None and spec.model in entry.fixed_temperature

    def builtin_turn_detection(self, spec: VendorSpec) -> bool:
        if spec.kind != "stt" or spec.model is None:
            return False
        return spec.model in self.entry("stt", spec.provider).builtin_turn_detection

    def with_builders(
        self,
        builders: Mapping[tuple[Kind, str], Builder] | None = None,
        default_builder: Builder | None = None,
    ) -> AdapterRegistry:
        """Return a copy whose builders are replaced (fakes in tests and the harness)."""
        clone = AdapterRegistry(self.catalog)
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
