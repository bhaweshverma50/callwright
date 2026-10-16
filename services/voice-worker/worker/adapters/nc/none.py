"""Passthrough used when the config's ``noise_cancellation`` is null (off)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from worker.adapters.registry import VendorSpec


def build(spec: VendorSpec, creds: Mapping[str, str]) -> Any:
    return None
