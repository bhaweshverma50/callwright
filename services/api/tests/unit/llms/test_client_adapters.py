import pytest
from pydantic import SecretStr

from app.core.config import Settings
from app.llms.adapters.base import ChatMessage, ModelError
from app.llms.adapters.fake import FakeAdapter
from app.llms.adapters.openai import OpenAIAdapter
from app.llms.client import LlmClient, MissingKeyAdapter


def _client(**values: object) -> LlmClient:
    return LlmClient(Settings.model_construct(**values))


def test_azure_without_azure_config_falls_back_to_openai() -> None:
    client = _client(env="staging", openai_api_key=SecretStr("sk-test"))
    assert isinstance(client.adapter_for("azure_openai"), OpenAIAdapter)


async def test_missing_key_fails_loudly_outside_dev_and_test() -> None:
    for env in ("staging", "prod"):
        adapter = _client(env=env).adapter_for("azure_openai")
        assert isinstance(adapter, MissingKeyAdapter)
        with pytest.raises(ModelError, match="No API key is configured for azure_openai"):
            await adapter.complete("gpt-5.1", [ChatMessage("user", "hi")])


def test_dev_and_test_keep_the_offline_adapter() -> None:
    for env in ("dev", "test"):
        assert isinstance(_client(env=env).adapter_for("azure_openai"), FakeAdapter)
