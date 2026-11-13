"""Request bodies for /v1/connections (contracts/connectors.yaml). Responses are built as plain
dicts in ``service.py`` and validated by the contract tests."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class StartBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    connection_id: str | None = Field(default=None, pattern=r"^conn_")


class CompleteBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    state: str = Field(min_length=16, max_length=128)
    code: str | None = Field(default=None, min_length=1, max_length=2048)
    error: str | None = Field(default=None, max_length=200)
