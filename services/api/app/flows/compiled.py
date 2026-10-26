"""Pydantic model of the compiled flow (data-model section 4). ``export_schema.py`` writes its
JSON Schema to the worker, which checks every compiled flow it runs against it."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.flows.schemas import NodeType


class _Open(BaseModel):
    model_config = ConfigDict(extra="allow")


class CompiledTransition(_Open):
    edge_id: str
    function_name: str
    description: str
    target_node_id: str
    trigger: Literal["llm_condition"]
    label: str | None = None


class CompiledNode(_Open):
    type: NodeType
    label: str
    instructions: str | None = None
    begin_message: str | None = None
    context_strategy: Literal["inherit", "summarize", "reset"] | None = None
    llm: dict[str, Any] | None = None
    tts: dict[str, Any] | None = None
    stt: dict[str, Any] | None = None
    language: str | None = None
    tools: list[dict[str, Any]] | None = None
    kb_search: dict[str, Any] | None = None
    transitions: list[CompiledTransition] | None = None
    task: dict[str, Any] | None = None
    start: dict[str, Any] | None = None
    say: dict[str, Any] | None = None
    condition: dict[str, Any] | None = None
    extract: dict[str, Any] | None = None
    webhook: dict[str, Any] | None = None
    transfer: dict[str, Any] | None = None
    end: dict[str, Any] | None = None


class DeclaredVariable(BaseModel):
    name: str
    source_node_id: str
    type: str


class CompiledFlow(_Open):
    schema_version: Literal[1]
    flow_id: str
    graph_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    compiled_at: str
    entry_node_id: str
    persona_prompt: str
    builtin_variables: list[str]
    declared_variables: list[DeclaredVariable]
    nodes: dict[str, CompiledNode]
