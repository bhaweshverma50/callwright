"""Bodies for POST /v1/prompt-ai/generate (contracts/prompt_ai.yaml)."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.voices.catalog import DEFAULT_LANGUAGE


class ChatTurn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=8000)


class CurrentValues(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prompt: str | None = Field(default=None, max_length=50000)
    begin_message: str | None = Field(default=None, max_length=1000)
    dynamic_variables: list[Annotated[str, Field(max_length=64)]] = Field(default_factory=list, max_length=50)


class GenerateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: str | None = Field(default=None, pattern=r"^agt_[0-9A-HJKMNP-TV-Z]{26}$")
    language: str = Field(default=DEFAULT_LANGUAGE, max_length=16)
    messages: list[ChatTurn] = Field(min_length=1, max_length=40)
    current: CurrentValues | None = None
