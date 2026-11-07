"""Pydantic model of the compiled flow (data-model section 4) and ``compiled_view``, the one reader
of a version's ``config.flow.compiled`` for other features (007 evaluators, 008, 009).
``export_schema.py`` writes the model's JSON Schema to the worker, which checks every compiled
flow it runs against it."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
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


# A call that reaches one of these node types finished the flow.
TERMINAL_NODE_TYPES = frozenset({"end", "transfer"})


@dataclass(frozen=True)
class CompiledView:
    """The compiled flow of a config; empty when it has none (single prompt, or a draft with
    errors). ``nodes`` are the config's own node dicts, keyed by node id."""

    nodes: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    entry_node_id: str | None = None
    persona_prompt: str | None = None

    @property
    def present(self) -> bool:
        return bool(self.nodes)

    def node_type(self, node_id: str | None) -> str | None:
        value = self.nodes.get(node_id or "", {}).get("type")
        return str(value) if value else None

    def labels(self) -> dict[str, str]:
        return {node_id: str(node.get("label") or node_id) for node_id, node in self.nodes.items()}


def compiled_view(config: Mapping[str, Any]) -> CompiledView:
    flow = config.get("flow")
    compiled = flow.get("compiled") if isinstance(flow, Mapping) else None
    if not isinstance(compiled, Mapping):
        return CompiledView()
    raw = compiled.get("nodes")
    nodes = {str(k): v for k, v in raw.items() if isinstance(v, Mapping)} if isinstance(raw, Mapping) else {}
    entry = compiled.get("entry_node_id")
    persona = compiled.get("persona_prompt")
    return CompiledView(nodes, str(entry) if entry else None, str(persona) if persona else None)
