"""Request bodies of contracts/simulator.yaml (008 T048). Responses are dicts built in
``service.run_view``, ``experiment_view`` and ``comparison``."""

from __future__ import annotations

from typing import Any, Literal

from callwright_contract.values import SimulationEndReason
from pydantic import BaseModel, ConfigDict, Field, model_validator

SimMode = Literal["replay", "persona"]


class SimTarget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["published", "draft", "version", "variant"] = "published"
    agent_version_id: str | None = Field(default=None, pattern=r"^agv_")
    config: dict[str, Any] | None = None
    label: str | None = Field(default=None, max_length=60)


class SimSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_caller_turns: int = Field(default=20, ge=1, le=50)
    missing_mock_policy: Literal["synthesize", "error"] = "synthesize"
    persona_model: str | None = None


class PersonaBrief(BaseModel):
    model_config = ConfigDict(extra="forbid")

    goal: str = Field(min_length=1, max_length=1000)
    known_facts: list[str] = Field(default_factory=list, max_length=30)
    temperament: str = Field(default="", max_length=300)
    speaking_style: str = Field(default="", max_length=300)
    constraints: list[str] = Field(default_factory=list, max_length=20)
    opening_line: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def _items(self) -> PersonaBrief:
        for name in ("known_facts", "constraints"):
            if any(len(v) > 300 for v in getattr(self, name)):
                raise ValueError(f"each {name} entry is at most 300 characters")
        return self


class PreflightBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: str = Field(pattern=r"^agt_")
    mode: SimMode
    target: SimTarget
    base_call_ids: list[str] | None = Field(default=None, max_length=1000)
    dataset_id: str | None = Field(default=None, pattern=r"^ds_")


class StartRunBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: str = Field(pattern=r"^agt_")
    mode: SimMode
    base_call_id: str | None = Field(default=None, pattern=r"^call_")
    target: SimTarget | None = None
    persona_brief: PersonaBrief | None = None
    dynamic_variables: dict[str, str] | None = None
    settings: SimSettings | None = None


class StartExperimentBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: str = Field(pattern=r"^agt_")
    name: str | None = Field(default=None, max_length=120)
    mode: SimMode
    target: SimTarget | None = None
    base_call_ids: list[str] | None = Field(default=None, min_length=2, max_length=100)
    dataset_id: str | None = Field(default=None, pattern=r"^ds_")
    settings: SimSettings | None = None


class SimResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    status: Literal["completed", "failed"]
    end_reason: SimulationEndReason | None = None
    diverged_at_turn: int | None = None
    answer_source_counts: dict[str, int] = Field(default_factory=dict)
    persona_brief: dict[str, Any] | None = None
    usage: dict[str, Any] = Field(default_factory=dict)
    error_message: str | None = None
