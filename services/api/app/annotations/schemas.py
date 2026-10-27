"""Request body for ``PUT /calls/{call_id}/annotations/me`` (contracts/annotations.yaml)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict


class AnnotationPut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: Literal["good", "bad"]
    note: str | None = None
