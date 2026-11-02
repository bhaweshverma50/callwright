"""Request bodies of contracts/datasets.yaml (008 T078)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class DatasetCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=80)
    description: str | None = Field(default=None, max_length=500)
    agent_id: str = Field(pattern=r"^agt_")
    call_ids: list[str] | None = Field(default=None, max_length=1000)


class DatasetUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=80)
    description: str | None = Field(default=None, max_length=500)


class AddItems(BaseModel):
    model_config = ConfigDict(extra="forbid")

    call_ids: list[str] = Field(min_length=1, max_length=1000)


class EvaluateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    only_missing: bool = False
