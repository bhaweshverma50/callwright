"""Request bodies of contracts/test_cases.yaml (008 T027). Responses are built as dicts in
``service.case_view`` and ``category_view``."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

AgentIdField = Field(pattern=r"^agt_")


class CategoryCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=60)
    slug: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_]{1,39}$")
    color: str | None = Field(default=None, pattern=r"^#[0-9a-f]{6}$")


class TestCaseCreate(BaseModel):
    __test__ = False
    model_config = ConfigDict(extra="forbid")

    agent_id: str = AgentIdField
    name: str | None = Field(default=None, max_length=120)
    category: str
    user_prompt: str = Field(min_length=1, max_length=2000)
    expected_behaviour: str = Field(min_length=1, max_length=2000)
    dynamic_variables: dict[str, str] = Field(default_factory=dict)


class TestCaseUpdate(BaseModel):
    __test__ = False
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=120)
    category: str | None = None
    user_prompt: str | None = Field(default=None, min_length=1, max_length=2000)
    expected_behaviour: str | None = Field(default=None, min_length=1, max_length=2000)
    dynamic_variables: dict[str, str] | None = None


class ImportBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: str = AgentIdField
    dry_run: bool = False
    format: str | None = None
    # Rows are checked one by one in the service so a bad row never rejects the whole file.
    test_cases: list[Any] = Field(max_length=500)


class GenerateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: str = AgentIdField
    category: str | None = None
    count: int = Field(default=5, ge=1, le=20)
    guidance: str | None = Field(default=None, max_length=1000)
