"""Request bodies of contracts/simulator.yaml (008 T048). Responses are dicts built in
``service.run_view``, ``experiment_view`` and ``comparison``."""

from __future__ import annotations

from typing import Any, Literal

from callwright_contract.textsim import PersonaBrief, SimMode, SimSettings
from pydantic import BaseModel, ConfigDict, Field


class SimTarget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["published", "draft", "version", "variant"] = "published"
    agent_version_id: str | None = Field(default=None, pattern=r"^agv_")
    config: dict[str, Any] | None = None
    label: str | None = Field(default=None, max_length=60)


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
