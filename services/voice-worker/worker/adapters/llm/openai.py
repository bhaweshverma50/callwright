"""OpenAI chat completions LLM."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from worker.adapters.llm import openai_kwargs
from worker.adapters.registry import VendorSpec


def build(spec: VendorSpec, creds: Mapping[str, str]) -> Any:
    from livekit.plugins import openai

    return openai.LLM(
        model=spec.model or "gpt-5.1",
        api_key=creds.get("api_key", ""),
        **openai_kwargs(spec.options, creds),
    )
