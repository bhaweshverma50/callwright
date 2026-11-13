"""Request and response bodies for /v1/account/deletion."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class DeletionRequest(BaseModel):
    confirm_workspace_name: str = Field(max_length=200)
    password: str | None = Field(default=None, max_length=128)
    confirm_email: str | None = Field(default=None, max_length=254)


class DeletionScheduled(BaseModel):
    requested_at: datetime
    scheduled_at: datetime
