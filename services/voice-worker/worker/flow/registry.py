"""Node handler registry (T055): the extension point for non-conversational node types.

A handler runs one node and says where the call goes next (:class:`Move`) or that the call is
over (:class:`Stop`). Conversational nodes (agent, task) are not handlers: the executor stops
on them and the runtime hands the call to that node's agent.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from worker.flow.executor import FlowRun

CONVERSATIONAL = frozenset({"agent", "task"})


@dataclass(frozen=True)
class Move:
    target: str
    trigger: str
    edge_id: str | None = None
    label: str | None = None
    function_name: str | None = None
    model_ms: int | None = None
    variables: Mapping[str, Any] = field(default_factory=dict)
    note: str | None = None


@dataclass(frozen=True)
class Stop:
    reason: str


Outcome = Move | Stop
NodeHandler = Callable[["FlowRun", str, Mapping[str, Any]], Awaitable[Outcome]]


class UnknownNodeType(ValueError):
    pass


_handlers: dict[str, NodeHandler] = {}


def register(node_type: str, handler: NodeHandler) -> None:
    if node_type in CONVERSATIONAL:
        raise ValueError(f"{node_type} nodes are conversational; they have no handler")
    _handlers[node_type] = handler


def handler_for(node_type: str) -> NodeHandler:
    try:
        return _handlers[node_type]
    except KeyError:
        raise UnknownNodeType(node_type) from None


def registered() -> frozenset[str]:
    return frozenset(_handlers)


def check_types(nodes: Mapping[str, Mapping[str, Any]]) -> None:
    """Reject a compiled flow with a node type nothing can run (before the call starts)."""
    for node_id, node in nodes.items():
        node_type = str(node.get("type"))
        if node_type not in CONVERSATIONAL and node_type not in _handlers:
            raise UnknownNodeType(f"{node_id}: {node_type}")
