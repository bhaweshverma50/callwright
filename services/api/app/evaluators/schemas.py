"""Request bodies for the evaluators module (contracts/evaluators.yaml). Config rules are checked
by the service so each message names its field."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class CustomInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    display_name: str
    description: str | None = None
    evaluator_type: str
    config: dict[str, Any]


class CustomPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str | None = None
    description: str | None = None
    config: dict[str, Any] | None = None


class TrialInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evaluator_type: str
    config: dict[str, Any]
    call_id: str
