"""Azure OpenAI LLM (default launch provider). Deployment names equal the model ids.

When the worker has no Azure OpenAI credentials but has an OpenAI key, the credentials carry
``fallback_openai_api_key`` (``WorkerSettings.vendor_credentials``) and the same model runs on
OpenAI directly, so agents on the default provider still work on an OpenAI-only deployment.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from worker.adapters.llm import temperature_kwargs
from worker.adapters.registry import VendorSpec

DEFAULT_API_VERSION = "2024-10-21"


def build(spec: VendorSpec, creds: Mapping[str, str]) -> Any:
    from livekit.plugins import openai

    model = spec.model or "gpt-5.1"
    fallback = creds.get("fallback_openai_api_key")
    if fallback:
        return openai.LLM(model=model, api_key=fallback, **temperature_kwargs(spec.options))
    return openai.LLM.with_azure(
        model=model,
        azure_endpoint=creds.get("endpoint") or "https://callwright.openai.azure.com",
        azure_deployment=creds.get("deployment") or model,
        api_version=creds.get("api_version") or DEFAULT_API_VERSION,
        api_key=creds.get("api_key", ""),
        **temperature_kwargs(spec.options),
    )
