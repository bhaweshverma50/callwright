"""Request and response bodies for /v1/phone-numbers (contracts/phone_numbers.yaml)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.channels import validation

ULID = "[0-9A-HJKMNP-TV-Z]{26}"
AGENT_ID = f"^agt_{ULID}$"
Transport = Literal["auto", "udp", "tcp", "tls"]


def check_e164(value: str) -> str:
    try:
        return validation.parse_e164(value)
    except validation.InvalidValue as exc:
        raise ValueError(str(exc)) from None


def _termination(value: str) -> str:
    try:
        validation.parse_termination(value)
    except validation.InvalidValue as exc:
        raise ValueError(str(exc)) from None
    return value


def _cidrs(value: list[str]) -> list[str]:
    try:
        return validation.parse_cidrs(value)
    except validation.InvalidValue as exc:
        raise ValueError(str(exc)) from None


def check_webhook_format(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    if not value.lower().startswith(("https://", "http://")):
        raise ValueError("Enter an https address, for example https://crm.example.com/callwright.")
    return value


class PhoneNumberImport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    e164: str
    label: str = Field(min_length=1, max_length=100)
    termination_address: str = Field(max_length=260)
    transport: Transport = "auto"
    auth_username: str | None = Field(default=None, max_length=128)
    auth_password: str | None = Field(default=None, max_length=256)
    inbound_allowed_cidrs: list[str] = Field(default_factory=list, max_length=20)
    inbound_agent_id: str | None = Field(default=None, pattern=AGENT_ID)
    outbound_agent_id: str | None = Field(default=None, pattern=AGENT_ID)
    inbound_webhook_url: str | None = Field(default=None, max_length=2048)

    @field_validator("e164")
    @classmethod
    def _v_e164(cls, value: str) -> str:
        return check_e164(value)

    @field_validator("termination_address")
    @classmethod
    def _v_term(cls, value: str) -> str:
        return _termination(value)

    @field_validator("inbound_allowed_cidrs")
    @classmethod
    def _v_cidrs(cls, value: list[str]) -> list[str]:
        return _cidrs(value)

    @field_validator("inbound_webhook_url")
    @classmethod
    def _v_hook(cls, value: str | None) -> str | None:
        return check_webhook_format(value)

    @field_validator("label")
    @classmethod
    def _label(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Enter a label.")
        return value


class PhoneNumberUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str | None = Field(default=None, min_length=1, max_length=100)
    termination_address: str | None = Field(default=None, max_length=260)
    transport: Transport | None = None
    auth_username: str | None = Field(default=None, max_length=128)
    auth_password: str | None = Field(default=None, max_length=256)
    remove_auth_password: bool | None = None
    inbound_allowed_cidrs: list[str] | None = Field(default=None, max_length=20)
    inbound_agent_id: str | None = Field(default=None, pattern=AGENT_ID)
    outbound_agent_id: str | None = Field(default=None, pattern=AGENT_ID)
    inbound_webhook_url: str | None = Field(default=None, max_length=2048)

    @field_validator("termination_address")
    @classmethod
    def _v_term(cls, value: str | None) -> str | None:
        return None if value is None else _termination(value)

    @field_validator("inbound_allowed_cidrs")
    @classmethod
    def _v_cidrs(cls, value: list[str] | None) -> list[str] | None:
        return None if value is None else _cidrs(value)

    @field_validator("inbound_webhook_url")
    @classmethod
    def _v_hook(cls, value: str | None) -> str | None:
        return check_webhook_format(value)


class PhoneNumberOut(BaseModel):
    id: str
    e164: str
    label: str
    termination_address: str
    transport: str
    auth_username: str | None
    has_auth_password: bool
    inbound_allowed_cidrs: list[str]
    inbound_agent_id: str | None
    outbound_agent_id: str | None
    inbound_webhook_url: str | None
    direct_uri: str
    status: str
    status_detail: str | None
    active_call_count: int
    created_at: str
    updated_at: str
