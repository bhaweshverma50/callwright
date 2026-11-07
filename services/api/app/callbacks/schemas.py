"""Request bodies (contracts/callbacks.yaml)."""

from __future__ import annotations

from datetime import datetime

from callwright_contract.values import CALLBACK_MAX_NOTE_CHARS
from callwright_contract.variables import MAX_VARIABLES, NAME
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator

from app.channels.phone_numbers.schemas import AGENT_ID, check_e164
from app.outbound.schemas import VariableValue

# One slot stays free for ``callback_note``.
MAX_CARRIED_VARIABLES = MAX_VARIABLES - 1


class CallbackCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    to_number: str
    from_number: str
    agent_id: str | None = Field(default=None, pattern=AGENT_ID)
    scheduled_at: AwareDatetime
    recipient_timezone: str | None = Field(default=None, max_length=64)
    note: str = Field(default="", max_length=CALLBACK_MAX_NOTE_CHARS)
    dynamic_variables: dict[str, VariableValue] = Field(
        default_factory=dict, max_length=MAX_CARRIED_VARIABLES
    )

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


def parse_local(value: str) -> datetime:
    """ISO 8601 date-time with or without an offset (``Z`` allowed); raises ``ValueError``."""
    text = value.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    return datetime.fromisoformat(text)
