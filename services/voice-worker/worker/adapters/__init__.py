"""Vendor adapters: one module per vendor under ``<kind>/<provider>.py`` (Principle I)."""

from worker.adapters.registry import (
    AdapterRegistry,
    UnsupportedLanguage,
    UnsupportedVendor,
    VendorNotConfigured,
    VendorSpec,
)

__all__ = [
    "AdapterRegistry",
    "UnsupportedLanguage",
    "UnsupportedVendor",
    "VendorNotConfigured",
    "VendorSpec",
]
