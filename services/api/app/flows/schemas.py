"""Flow shapes (contracts/flows.yaml, data-model sections 2 to 9; T008).

The graph is validated structurally here (ids, types, triggers, lengths, the 200 node and 500
edge limits). Node configs stay plain objects on the wire: drafts may hold incomplete or out of
range values, which ``validation.py`` reports as issues instead of refusing the save (FR-006,
FR-045). ``HttpRequestSpec`` and ``TransferSpec`` come from 005 and are used by the validator
and the compiler for webhook and transfer nodes.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.agents.schemas import NAME_MAX
from app.tools.schemas import HttpRequestSpec, TransferSpec

__all__ = [
    "AgentSettingsChange",
    "AssistantMessage",
    "AssistantRequest",
    "CreateFlowAgentRequest",
    "Edge",
    "FlowGraph",
    "HttpRequestSpec",
    "Node",
    "NodeType",
    "PublishRequest",
    "Rule",
    "SaveFlowRequest",
    "TransferSpec",
    "Trigger",
    "ValidateRequest",
]

MAX_NODES = 200
MAX_EDGES = 500
NODE_ID = r"^n_[a-z0-9]{8}$"
EDGE_ID = r"^e_[a-z0-9]{8}$"
FUNCTION_NAME = r"^route_to_[a-z0-9_]{1,48}$"

NodeType = Literal[
    "start", "agent", "task", "condition", "say", "extract_variable", "webhook", "transfer", "end"
]
NODE_TYPES: tuple[NodeType, ...] = (
    "start",
    "agent",
    "task",
    "condition",
    "say",
    "extract_variable",
    "webhook",
    "transfer",
    "end",
)
CONVERSATIONAL: frozenset[str] = frozenset({"agent", "task"})
Trigger = Literal["llm_condition", "category", "rule", "else", "always", "success", "failure"]
Operator = Literal["equals", "not_equals", "contains", "matches", "exists", "gt", "lt"]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Position(BaseModel):
    x: float
    y: float


class Viewport(BaseModel):
    x: float = 0
    y: float = 0
    zoom: float = Field(default=1, ge=0.1, le=4)


class Node(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str = Field(pattern=NODE_ID)
    type: NodeType
    label: str = Field(min_length=1, max_length=80)
    position: Position
    config: dict[str, Any] = Field(default_factory=dict)


class Rule(BaseModel):
    variable: str = Field(max_length=120)
    operator: Operator
    value: str | None = Field(default=None, max_length=500)


class Edge(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str = Field(pattern=EDGE_ID)
    source: str = Field(pattern=NODE_ID)
    target: str = Field(pattern=NODE_ID)
    trigger: Trigger
    label: str | None = Field(default=None, max_length=60)
    condition: str | None = Field(default=None, max_length=1000)
    function_name: str | None = Field(default=None, pattern=FUNCTION_NAME)
    category: str | None = Field(default=None, max_length=60)
    rule: Rule | None = None
    sort_order: int = Field(default=0, ge=0)


class FlowGraph(_Model):
    nodes: list[Node] = Field(min_length=1, max_length=MAX_NODES)
    edges: list[Edge] = Field(default_factory=list, max_length=MAX_EDGES)
    viewport: Viewport = Field(default_factory=Viewport)


def _name(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("Agent name is required")
    if len(value) > NAME_MAX:
        raise ValueError(f"Use at most {NAME_MAX} characters")
    return value


class CreateFlowAgentRequest(_Model):
    name: str = Field(max_length=NAME_MAX)
    language: str = Field(min_length=1, max_length=16)

    @field_validator("name")
    @classmethod
    def _check_name(cls, value: str) -> str:
        return _name(value)


class AgentSettingsChange(_Model):
    expected_draft_revision: int = Field(ge=1)
    changes: dict[str, Any] = Field(min_length=1)


class SaveFlowRequest(_Model):
    name: str = Field(max_length=NAME_MAX)
    graph: FlowGraph
    agent_settings: AgentSettingsChange | None = None

    @field_validator("name")
    @classmethod
    def _check_name(cls, value: str) -> str:
        return _name(value)


class ValidateRequest(_Model):
    graph: FlowGraph | None = None


class PublishRequest(_Model):
    expected_revision: int = Field(ge=1)
    release_notes: str | None = Field(default=None, max_length=2000)


class AssistantMessage(_Model):
    role: Literal["user", "assistant"]
    content: Annotated[str, Field(max_length=8000)]


class AssistantRequest(_Model):
    messages: list[AssistantMessage] = Field(min_length=1, max_length=50)
    base_revision: int = Field(ge=1)
    graph: FlowGraph | None = None


def graph_json(graph: FlowGraph) -> dict[str, Any]:
    """The stored form of a graph (ids, configs and positions as sent, no unset extras)."""
    return graph.model_dump(mode="json", exclude_none=True)
