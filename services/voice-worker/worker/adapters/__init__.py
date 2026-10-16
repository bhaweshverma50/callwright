"""Vendor adapters: one module per vendor under ``<kind>/<provider>.py`` (Principle I)."""

from worker.adapters.registry import (
    AdapterRegistry,
    CatalogEntry,
    UnsupportedLanguage,
    UnsupportedVendor,
    VendorSpec,
    load_catalog,
)

__all__ = [
    "AdapterRegistry",
    "CatalogEntry",
    "UnsupportedLanguage",
    "UnsupportedVendor",
    "VendorSpec",
    "load_catalog",
]
