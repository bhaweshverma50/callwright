"""Request bodies for knowledge sources (contracts/connectors.yaml). Responses are plain dicts built
in ``service.py`` and checked by the contract tests."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class SourceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    connection_id: str = Field(pattern=r"^conn_")
    root_kind: Literal["folder", "shared_drive"]
    root_id: str = Field(min_length=1, max_length=200, pattern=r"^[A-Za-z0-9_-]+$")
    drive_id: str | None = Field(default=None, max_length=200, pattern=r"^[A-Za-z0-9_-]+$")
    include_subfolders: bool = True
    interval_minutes: int = Field(default=15, ge=5, le=1440)


class SourceUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    include_subfolders: bool | None = None
    interval_minutes: int | None = Field(default=None, ge=5, le=1440)
