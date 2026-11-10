"""A vendor plugin that refuses an empty key ends the call with unsupported_vendor, not a crash."""

from __future__ import annotations

from typing import Any

import pytest

from tests.unit.conftest import make_runtime
from worker.adapters.registry import AdapterRegistry, VendorNotConfigured, VendorSpec
from worker.pipeline import build_components, plan_session


def _registry(error: Exception) -> AdapterRegistry:
    def keyless(spec: VendorSpec, creds: Any) -> Any:
        if spec.provider == "sarvam":
            raise error
        return object()

    return AdapterRegistry().with_builders(default_builder=keyless)


def _plan(registry: AdapterRegistry) -> Any:
    config = {
        "language": "hi",
        "stt": {"provider": "sarvam", "model": "saaras:v3"},
        "llm": {"provider": "openai", "model": "gpt-5-mini"},
        "tts": {"provider": "elevenlabs", "model": "eleven_turbo_v2_5"},
        "noise_cancellation": None,
    }
    return plan_session(make_runtime(config), registry)


def test_missing_key_becomes_unsupported_vendor_diagnostic() -> None:
    registry = _registry(ValueError("Sarvam API key is required"))
    with pytest.raises(VendorNotConfigured) as caught:
        build_components(_plan(registry), registry, {"sarvam": {"api_key": ""}})
    assert caught.value.diagnostic == "unsupported_vendor:stt/sarvam"


def test_value_error_with_a_key_is_not_masked() -> None:
    registry = _registry(ValueError("bad language"))
    with pytest.raises(ValueError, match="bad language"):
        build_components(_plan(registry), registry, {"sarvam": {"api_key": "k"}})
