"""Bodies for /v1/me/preferences (specs/013-guided-setup/contracts/preferences.yaml)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

OnboardingStatus = Literal["not_started", "in_progress", "skipped", "completed"]
# A step id from the web app's tour, kept opaque here: lower case words joined by - or _.
STEP_PATTERN = r"^[a-z][a-z0-9_-]{0,39}$"


class OnboardingOut(BaseModel):
    status: OnboardingStatus
    step: str | None
    updated_at: datetime | None


class PreferencesOut(BaseModel):
    onboarding: OnboardingOut


class OnboardingUpdate(BaseModel):
    """Only the fields sent change; at least one. ``step: null`` clears the step."""

    model_config = ConfigDict(extra="forbid")

    status: OnboardingStatus | None = None
    step: str | None = Field(default=None, pattern=STEP_PATTERN)

    @model_validator(mode="after")
    def _at_least_one(self) -> OnboardingUpdate:
        if not self.model_fields_set:
            raise ValueError("Send status, step or both.")
        if "status" in self.model_fields_set and self.status is None:
            raise ValueError("status cannot be null.")
        return self


class PreferencesUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    onboarding: OnboardingUpdate
