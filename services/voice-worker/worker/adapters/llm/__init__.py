"""Language model adapters. Each module exposes ``build(spec, creds) -> llm.LLM``."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

# Every launch model (gpt-5 family) only accepts temperature 1.0 (002 data-model 8.2), so the
# parameter is sent only when it differs from the vendor default.
DEFAULT_TEMPERATURE = 1.0


def temperature_kwargs(options: Mapping[str, Any]) -> dict[str, Any]:
    temperature = options.get("temperature")
    if temperature is None or float(temperature) == DEFAULT_TEMPERATURE:
        return {}
    return {"temperature": float(temperature)}
