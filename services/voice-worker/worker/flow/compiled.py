"""The compiled flow a call runs (004 data-model section 4).

``compiled_schema.json`` is written by the API from its ``CompiledFlow`` model
(``app.flows.export_schema``); :func:`load_compiled` checks every compiled flow against it before
the call starts, and the schema's ``schema_version`` is the version this worker runs. The
compiler writes every value of a node section, so the views below read them as given.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, fields
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
    def of(cls, section: Mapping[str, Any]) -> Self:
        """The view of a node section (checked against the schema at load)."""
        return cls(**{f.name: section[f.name] for f in fields(cls)})  # type: ignore[arg-type]


@dataclass(frozen=True)
class TaskSection(_View):
    json_schema: Mapping[str, Any]
    max_rounds: int
    success_target: str | None
    success_edge_id: str | None


@dataclass(frozen=True)
class StartSection(_View):
    start_speaker: Literal["agent", "user"]
    greeting_type: Literal["static", "generated"]
    greeting: str
    next: str | None
    edge_id: str | None


@dataclass(frozen=True)
class EndSection(_View):
    message: str
    reason: str
