"""Request bodies for /v1/whatsapp (contracts/whatsapp.yaml)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.phone_numbers.schemas import AGENT_ID, check_e164, check_webhook_format

GRAPH_VERSION = r"^v?\d+\.\d+$"


class WhatsAppChannelCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    meta_phone_number_id: str = Field(pattern=r"^\d{5,32}$")
    e164: str
    label: str = Field(min_length=1, max_length=100)
    access_token: str = Field(min_length=1, max_length=1024)
    verify_token: str = Field(min_length=8, max_length=128)
    app_secret: str = Field(min_length=1, max_length=1024)
    graph_api_version: str | None = Field(default=None, pattern=GRAPH_VERSION)
    inbound_agent_id: str | None = Field(default=None, pattern=AGENT_ID)
    inbound_webhook_url: str | None = Field(default=None, max_length=2048)

    @field_validator("e164")
    @classmethod
    def _e164(cls, value: str) -> str:
        return check_e164(value)

    @field_validator("inbound_webhook_url")
    @classmethod
    def _hook(cls, value: str | None) -> str | None:
        return check_webhook_format(value)

    @field_validator("label", "access_token", "app_secret")
    @classmethod
    def _strip(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("This field is required.")
        return value


class WhatsAppChannelUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str | None = Field(default=None, min_length=1, max_length=100)
    access_token: str | None = Field(default=None, max_length=1024)
    verify_token: str | None = Field(default=None, min_length=8, max_length=128)
    app_secret: str | None = Field(default=None, min_length=1, max_length=1024)
    graph_api_version: str | None = Field(default=None, pattern=GRAPH_VERSION)
    inbound_agent_id: str | None = Field(default=None, pattern=AGENT_ID)
    inbound_webhook_url: str | None = Field(default=None, max_length=2048)

    @field_validator("inbound_webhook_url")
    @classmethod
    def _hook(cls, value: str | None) -> str | None:
        return check_webhook_format(value)


class CallerRouteCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    caller_number: str = Field(min_length=1, max_length=32)
    agent_id: str = Field(pattern=AGENT_ID)


class CallerRouteUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: str = Field(pattern=AGENT_ID)
