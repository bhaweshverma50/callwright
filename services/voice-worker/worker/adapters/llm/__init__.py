"""Language model adapters. Each module exposes ``build(spec, creds) -> llm.LLM``."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

# Every launch model (gpt-5 family) only accepts temperature 1.0 (002 data-model 8.2), so the
# parameter is sent only when it differs from the vendor default.
DEFAULT_TEMPERATURE = 1.0


# Model families that reject any temperature other than the vendor default.
FIXED_TEMPERATURE_PREFIXES = ("gpt-5",)


def supports_temperature(model: str | None) -> bool:
    """False when ``model`` only runs at the vendor default temperature, so callers that want a
    different one (008's simulated caller asks for 0.7) leave it unset instead of failing."""
    return not str(model or "").startswith(FIXED_TEMPERATURE_PREFIXES)


def temperature_kwargs(options: Mapping[str, Any]) -> dict[str, Any]:
    temperature = options.get("temperature")
    if temperature is None or float(temperature) == DEFAULT_TEMPERATURE:
        return {}
    return {"temperature": float(temperature)}


def openai_kwargs(options: Mapping[str, Any], creds: Mapping[str, str]) -> dict[str, Any]:
    """Keyword arguments shared by the OpenAI-hosted adapters (temperature, service tier)."""
    kwargs = temperature_kwargs(options)
    if creds.get("service_tier"):
        kwargs["service_tier"] = creds["service_tier"]
    return kwargs
