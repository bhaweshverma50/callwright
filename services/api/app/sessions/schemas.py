"""Browser test call request and session (contracts/sessions.yaml, 003 T030)."""

from __future__ import annotations

import json
from typing import Annotated, Any

from callwright_contract.variables import MAX_VALUE_CHARS, MAX_VARIABLES, NAME
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

ULID = "[0-9A-HJKMNP-TV-Z]{26}"
MAX_METADATA_BYTES = 4096
MAX_METADATA_KEYS = 20

VariableValue = Annotated[str, StringConstraints(max_length=MAX_VALUE_CHARS)]


class WebCallRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: str = Field(pattern=f"^agt_{ULID}$")
    version: str = Field(default="draft", pattern=f"^(draft|published|agv_{ULID})$")
    dynamic_variables: dict[str, VariableValue] = Field(default_factory=dict, max_length=MAX_VARIABLES)
    metadata: dict[str, Any] = Field(default_factory=dict, max_length=MAX_METADATA_KEYS)

    @field_validator("dynamic_variables")
    @classmethod
    def _names(cls, value: dict[str, str]) -> dict[str, str]:
        bad = [name for name in value if not NAME.match(name)]
        if bad:
            raise ValueError(
                f"Variable names start with a letter or underscore and use letters, digits and "
                f"underscores (max 64 characters): {', '.join(sorted(bad))[:200]}"
            )
        return value

    @field_validator("metadata")
    @classmethod
    def _metadata_size(cls, value: dict[str, Any]) -> dict[str, Any]:
        if len(json.dumps(value, separators=(",", ":"), default=str).encode()) > MAX_METADATA_BYTES:
            raise ValueError("Metadata is at most 4 KB when serialized.")
        return value


class WebCallSession(BaseModel):
    call_id: str
    agent_version_id: str
    room_name: str
    server_url: str
    participant_token: str
    expires_at: str
    status: str = "queued"
    missing_variables: list[str] = Field(default_factory=list)
    ignored_overrides: list[str] = Field(default_factory=list)
