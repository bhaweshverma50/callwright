"""Request bodies for the analysis_vars module (contracts/analysis_vars.yaml). Field rules are
checked by the service so every message names the field the way the editor shows it."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class VariableInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    type: str
    description: str
    choices: list[str] | None = None


class VariablePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    type: str | None = None
    description: str | None = None
    choices: list[str] | None = None


class VariableOrder(BaseModel):
    model_config = ConfigDict(extra="forbid")

    variable_ids: list[str]
