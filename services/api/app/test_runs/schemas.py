"""Request bodies of contracts/test_runs.yaml (008 T032). Responses are built as dicts in
``service.run_view`` and ``result_view``."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class TestTarget(BaseModel):
    __test__ = False
    model_config = ConfigDict(extra="forbid")

    type: Literal["draft", "published", "version"] = "draft"
    agent_version_id: str | None = Field(default=None, pattern=r"^agv_")


class StartRun(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: str = Field(pattern=r"^agt_")
    test_case_ids: list[str] | None = Field(default=None, max_length=500)
    category: str | None = None
    target: TestTarget | None = None
    judge_model: str | None = None


class OverrideBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    override_status: Literal["passed", "failed"] | None
    override_note: str | None = Field(default=None, max_length=500)


class ToolCallRecord(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    output: str | None = None
    answer_source: Literal["mock", "recorded", "synthesized", "error"] | None = None


class CaseResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    status: Literal["completed", "error"]
    agent_response: str | None = None
    tool_calls: list[ToolCallRecord] = Field(default_factory=list)
    nodes_visited: list[str] = Field(default_factory=list)
    usage: dict[str, Any] = Field(default_factory=dict)
    duration_ms: int | None = None
    error_message: str | None = None
