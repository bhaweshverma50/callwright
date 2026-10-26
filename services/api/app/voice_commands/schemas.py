"""Voice command request shapes (006, contracts/voice_commands.yaml)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class RegisteredAction(BaseModel):
    model_config = ConfigDict(extra="ignore")

    key: str = Field(max_length=64)
    label: str = Field(max_length=120)
    params_schema: dict[str, Any] | None = None


class VisibleEntity(BaseModel):
    model_config = ConfigDict(extra="ignore")

    kind: Literal["agent", "flow", "call", "evaluator"] | None = None
    id: str | None = Field(default=None, max_length=64)
    name: str | None = Field(default=None, max_length=120)


class VisualState(BaseModel):
    model_config = ConfigDict(extra="ignore")

    current_route: str = Field(max_length=300)
    page_title: str | None = Field(default=None, max_length=120)
    current_datetime: str
    timezone: str = Field(max_length=64)
    available_actions: list[RegisteredAction] = Field(default_factory=list, max_length=50)
    highlightable_elements: list[str] = Field(default_factory=list, max_length=50)
    visible_entities: list[VisibleEntity] = Field(default_factory=list, max_length=50)
    open_panels: list[str] = Field(default_factory=list, max_length=20)


class HistoryItem(BaseModel):
    role: Literal["user", "copilot"]
    content: str = Field(max_length=1000)


class InterpretRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    transcript: str = Field(min_length=1, max_length=1000)
    visual_state: VisualState
    conversation_history: list[HistoryItem] = Field(default_factory=list, max_length=12)
