"""Bodies for /v1/me and /v1/workspaces (contracts/workspaces.yaml)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.pricing.engine import fmt6
from app.workspaces.service import MeView


class UserOut(BaseModel):
    id: str
    email: str
    email_verified: bool
    is_admin: bool
    has_password: bool
    deletion_scheduled_at: datetime | None = None


class WorkspaceOut(BaseModel):
    id: str
    name: str
    concurrency_limit: int
    recording_default: bool
    created_at: datetime


class MeOut(BaseModel):
    user: UserOut
    workspace: WorkspaceOut
    balance_usd: str

    @classmethod
    def from_view(cls, view: MeView) -> MeOut:
        return cls(
            user=UserOut(
                id=view.user.id,
                email=view.user.email,
                email_verified=view.user.email_verified_at is not None,
                is_admin=view.user.is_admin,
                has_password=view.has_password,
                deletion_scheduled_at=view.user.deletion_scheduled_at,
            ),
            workspace=WorkspaceOut.model_validate(view.workspace, from_attributes=True),
            balance_usd=fmt6(view.balance_usd),
        )


class WorkspaceUpdate(BaseModel):
    """Settings save (FR-017): only the fields sent change; at least one field."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=80)
    recording_default: bool | None = None

    @field_validator("name")
    @classmethod
    def _not_blank(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("Enter a workspace name.")
        return value.strip() if value is not None else None

    @model_validator(mode="after")
    def _at_least_one(self) -> WorkspaceUpdate:
        if not self.model_fields_set:
            raise ValueError("Send at least one field to change.")
        if "name" in self.model_fields_set and self.name is None:
            raise ValueError("The workspace name cannot be empty.")
        if "recording_default" in self.model_fields_set and self.recording_default is None:
            raise ValueError("recording_default must be true or false.")
        return self
