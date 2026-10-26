"""Request shapes for the knowledge endpoints (contracts/knowledge.yaml, T058). Responses are
built by ``service.kb_view`` and ``service.document_view`` (derived KB status and ``attachable``)."""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class KnowledgeBaseWrite(_Strict):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)


class CheckDuplicate(_Strict):
    file_name: str = Field(max_length=255)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    file_size: int = Field(ge=1)


class SearchRequest(_Strict):
    query: str = Field(min_length=1, max_length=1000)
    top_k: int = Field(default=4, ge=1, le=8)


class SetAgentKnowledge(_Strict):
    kb_ids: list[Annotated[str, Field(pattern=r"^kb_")]] = Field(max_length=10)


class InternalSearch(_Strict):
    call_id: str = Field(pattern=r"^call_")
    query: str = Field(min_length=1, max_length=1000)
    kb_ids: list[Annotated[str, Field(pattern=r"^kb_")]] = Field(min_length=1, max_length=10)
    top_k: int = Field(default=4, ge=1, le=8)
