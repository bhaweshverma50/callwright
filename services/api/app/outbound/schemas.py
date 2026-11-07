"""Request bodies for outbound calls and compliance settings (contracts/outbound.yaml)."""

from __future__ import annotations

import json
from typing import Annotated, Any

from callwright_contract.variables import MAX_VALUE_CHARS, MAX_VARIABLES, NAME
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from app.channels.phone_numbers.schemas import AGENT_ID, check_e164

MAX_METADATA_BYTES = 4096
VariableValue = Annotated[str, StringConstraints(max_length=MAX_VALUE_CHARS)]


class OutboundCallRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    to_number: str
    from_number: str
    agent_id: str | None = Field(default=None, pattern=AGENT_ID)
    dynamic_variables: dict[str, VariableValue] = Field(default_factory=dict, max_length=MAX_VARIABLES)
    metadata: dict[str, Any] = Field(default_factory=dict, max_length=20)
    ring_timeout_s: int = Field(default=30, ge=10, le=60)
    recipient_timezone: str | None = Field(default=None, max_length=64)

    @field_validator("to_number", "from_number")
    @classmethod
    def _numbers(cls, value: str) -> str:
        return check_e164(value)

    @field_validator("dynamic_variables")
    @classmethod
    def _names(cls, value: dict[str, str]) -> dict[str, str]:
        bad = [name for name in value if not NAME.match(name)]
        if bad:
            raise ValueError(
                "Variable names start with a letter or underscore and use letters, digits and "
                f"underscores (max 64 characters): {', '.join(sorted(bad))[:200]}"
            )
        return value

    @field_validator("metadata")
    @classmethod
    def _metadata_size(cls, value: dict[str, Any]) -> dict[str, Any]:
        if len(json.dumps(value, separators=(",", ":"), default=str).encode()) > MAX_METADATA_BYTES:
            raise ValueError("Metadata is at most 4 KB when serialized.")
        return value


class DncEntryCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    number: str = Field(min_length=1, max_length=32)
    default_region: str | None = Field(default=None, pattern="^[A-Z]{2}$")
    note: str | None = Field(default=None, max_length=200)


class CallingHoursUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    windows: dict[str, Any]
