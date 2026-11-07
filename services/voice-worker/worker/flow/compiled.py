"""The compiled flow a call runs (004 data-model section 4).

``compiled_schema.json`` is written by the API from its ``CompiledFlow`` model
(``app.flows.export_schema``); :func:`load_compiled` checks every compiled flow against it before
the call starts, and the schema's ``schema_version`` is the version this worker runs. Node
sections are read through the small views below, which carry the compiler's defaults for the
values it always writes (``app.flows.compiler``), so the runtime reads them in one place.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any, Literal, Self

from callwright_contract.diagnostics import FLOW_NOT_COMPILED

from worker import json_schema
from worker.flow import FlowRuntimeUnavailable

SCHEMA: Mapping[str, Any] = json.loads(
    Path(__file__).with_name("compiled_schema.json").read_text(encoding="utf-8")
)
SCHEMA_VERSION: int = SCHEMA["properties"]["schema_version"]["const"]


def load_compiled(config: Mapping[str, Any]) -> Mapping[str, Any]:
    """The claim's compiled flow, checked against the schema. Raises
    :class:`FlowRuntimeUnavailable` (``flow_not_compiled``) when there is none this worker can
    run."""
    flow = config.get("flow")
    compiled = flow.get("compiled") if isinstance(flow, Mapping) else None
    if not isinstance(compiled, Mapping) or compiled.get("schema_version") != SCHEMA_VERSION:
        raise FlowRuntimeUnavailable("the flow did not compile", diagnostic=FLOW_NOT_COMPILED)
    problem = json_schema.problem(SCHEMA, compiled, "flow")
    if problem is not None:
        raise FlowRuntimeUnavailable(
            f"the compiled flow does not match its schema: {problem}",
            diagnostic=FLOW_NOT_COMPILED,
        )
    return compiled


class _View:
    @classmethod
    def of(cls, section: Mapping[str, Any] | None) -> Self:
        """The view of a node section; absent or null values take the compiler's default."""
        names = {f.name for f in fields(cls)}  # type: ignore[arg-type]
        return cls(**{k: v for k, v in (section or {}).items() if k in names and v is not None})


@dataclass(frozen=True)
class ConversationNode(_View):
    """An agent or task node."""

    context_strategy: Literal["inherit", "summarize", "reset"] = "inherit"


@dataclass(frozen=True)
class TaskSection(_View):
    json_schema: Mapping[str, Any] = field(
        default_factory=lambda: {"type": "object", "properties": {}}
    )
    max_rounds: int = 5
    success_target: str | None = None
    success_edge_id: str | None = None


@dataclass(frozen=True)
class StartSection(_View):
    start_speaker: Literal["agent", "user"] = "agent"
    greeting_type: Literal["static", "generated"] = "static"
    greeting: str = ""
    next: str | None = None
    edge_id: str | None = None


@dataclass(frozen=True)
class EndSection(_View):
    message: str = ""
    reason: str = "call_completed"
