"""Worker settings: Azure OpenAI falls back to OpenAI when only an OpenAI key is configured."""

from __future__ import annotations

from typing import Any

from worker.adapters.llm import azure_openai
from worker.adapters.registry import VendorSpec
from worker.settings import WorkerSettings

GPT = VendorSpec(kind="llm", provider="azure_openai", model="gpt-5.1")


def settings(**env: str) -> WorkerSettings:
    base: dict[str, Any] = {
        "OPENAI_API_KEY": "",
        "AZURE_OPENAI_API_KEY": "",
        "AZURE_OPENAI_ENDPOINT": "",
    }
    return WorkerSettings.model_validate({**base, **env})


def test_openai_only_deployment_runs_azure_agents_on_openai() -> None:
    s = settings(OPENAI_API_KEY="sk-test")
    assert s.azure_openai_falls_back_to_openai()
    creds = s.vendor_credentials()["azure_openai"]
    assert creds["fallback_openai_api_key"] == "sk-test"
    llm = azure_openai.build(GPT, creds)
    assert llm.model == "gpt-5.1"
    assert str(llm._client.base_url) == "https://api.openai.com/v1/"


def test_configured_azure_is_used_as_is() -> None:
    s = settings(
        OPENAI_API_KEY="sk-test",
        AZURE_OPENAI_API_KEY="az-key",
        AZURE_OPENAI_ENDPOINT="https://cw.openai.azure.com",
    )
    assert not s.azure_openai_falls_back_to_openai()
    creds = s.vendor_credentials()["azure_openai"]
    assert "fallback_openai_api_key" not in creds
    llm = azure_openai.build(GPT, creds)
    assert str(llm._client.base_url).startswith("https://cw.openai.azure.com/")


def test_no_llm_keys_keeps_azure_without_fallback() -> None:
    s = settings()
    assert not s.azure_openai_falls_back_to_openai()
    assert "fallback_openai_api_key" not in s.vendor_credentials()["azure_openai"]
