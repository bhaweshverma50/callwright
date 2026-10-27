"""Request bodies for the evals module (contracts/evals.yaml)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class SettingPut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool
    overrides: dict[str, Any] | None = None
    is_headline: bool = False


class RerunBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evaluator_ids: list[str] | None = None
