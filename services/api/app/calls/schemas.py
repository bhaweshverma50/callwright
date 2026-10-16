"""Internal claim request (contracts/calls.yaml ``ClaimRequest``, 003 T032).

Field names match ``services/voice-worker/worker/internal_api.py`` (``ClaimRequest``,
``SipAttributes``). The response is built as a plain dict in ``calls.service`` and checked
against the contract by the contract tests.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class SipAttributes(BaseModel):
    model_config = ConfigDict(extra="allow")

    call_id: str | None = None
    trunk_id: str | None = None
    trunk_phone_number: str | None = None
    caller_number: str | None = None
    participant_identity: str | None = None


class ClaimRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str = Field(min_length=1, max_length=200)
    room_name: str = Field(min_length=1, max_length=200)
    worker_id: str = Field(min_length=1, max_length=200)
    dispatch_metadata: dict[str, Any]
    sip: SipAttributes | None = None
