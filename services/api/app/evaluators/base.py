"""Evaluator protocol and the data every evaluator reads (007 T008, research R3).

``EvalContext`` is built once per call by ``app.evals.context`` from the finalised transcript,
turn events, the agent version the call ran (never the current draft) and the call's recording
reference. Evaluators return ``EvalOutcome``: one ``ItemResult`` per call (call scope), per turn,
per flow node or per silence, plus model usage for judges. The runner turns items into the run
verdict with ``app.evals.scoring.run_verdict``.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any, ClassVar, Literal

from app.evals.scoring import Verdict

Scope = Literal["call", "turn", "flow_node"]
CostClass = Literal["free", "llm_judge"]
OutputKind = Literal["class", "anomaly", "audio_quality", "process_reward"]
AgentType = Literal["single_prompt", "flow"]
ALL_AGENT_TYPES: tuple[AgentType, ...] = ("single_prompt", "flow")
FLOW_ONLY: tuple[AgentType, ...] = ("flow",)


@dataclass(frozen=True)
class Message:
    """One spoken line. ``index`` is its position among messages (the judge's turn number)."""

    index: int
    role: Literal["agent", "user"]
    text: str
    turn_index: int | None = None
    started_ms: int | None = None


@dataclass(frozen=True)
class ToolEvent:
    name: str
    arguments: Mapping[str, Any] | None
    output: str | None
    is_error: bool
    ref: str | None = None
    after_message: int = -1  # index of the last message before the call (-1: before any)


@dataclass(frozen=True)
class FlowTransition:
    from_node_id: str | None
    to_node_id: str
    label: str | None = None


@dataclass(frozen=True)
class TurnLatency:
    turn_index: int
    e2e_ms: int


@dataclass(frozen=True)
class RecordingRef:
    key: str
    bucket: str | None


@dataclass
class EvalContext:
    call_id: str
    workspace_id: str
    agent_id: str
    agent_type: AgentType
    origin: str
    ended_at: datetime | None
    disconnect_reason: str | None
    config: Mapping[str, Any]
    messages: list[Message] = field(default_factory=list)
    tools: list[ToolEvent] = field(default_factory=list)
    transitions: list[FlowTransition] = field(default_factory=list)
    latencies: list[TurnLatency] = field(default_factory=list)
    recording: RecordingRef | None = None
    run_id: str = ""

    @property
    def agent_messages(self) -> list[Message]:
        return [m for m in self.messages if m.role == "agent"]

    @property
    def caller_spoke(self) -> bool:
        return any(m.role == "user" and m.text.strip() for m in self.messages)

    @property
    def kb_searches(self) -> list[ToolEvent]:
        return [t for t in self.tools if t.name in KB_TOOL_NAMES]

    @property
    def flow_nodes(self) -> Mapping[str, Mapping[str, Any]]:
        """Compiled flow nodes of the version the call ran (004), keyed by node id."""
        flow = self.config.get("flow")
        compiled = flow.get("compiled") if isinstance(flow, Mapping) else None
        nodes = compiled.get("nodes") if isinstance(compiled, Mapping) else None
        return nodes if isinstance(nodes, Mapping) else {}

    def node_label(self, node_id: str | None) -> str | None:
        if node_id is None:
            return None
        node = self.flow_nodes.get(node_id)
        label = node.get("label") if isinstance(node, Mapping) else None
        return str(label) if label else node_id

    def node_type(self, node_id: str | None) -> str | None:
        node = self.flow_nodes.get(node_id or "")
        value = node.get("type") if isinstance(node, Mapping) else None
        return str(value) if value else None

    def visited_nodes(self) -> list[str]:
        """Node ids in visit order (the entry node first), repeats kept."""
        if not self.transitions:
            return []
        first = self.transitions[0].from_node_id
        out = [first] if first else []
        out += [t.to_node_id for t in self.transitions]
        return out


KB_TOOL_NAMES = frozenset({"kb_search", "search_knowledge_base"})


@dataclass(frozen=True)
class ItemResult:
    verdict: Verdict
    score: float | None
    rationale: str
    turn_index: int | None = None
    flow_node_id: str | None = None
    flow_node_label: str | None = None
    start_ms: int | None = None
    duration_ms: int | None = None
    evidence: Mapping[str, Any] = field(default_factory=dict)


@dataclass
class EvalOutcome:
    items: list[ItemResult]
    rationale: str | None = None  # run-level text; derived from the items when None
    judge_model: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    raw_cost_usd: Decimal = Decimal(0)

    @classmethod
    def not_applicable(cls, reason: str) -> EvalOutcome:
        return cls([ItemResult("not_applicable", None, reason)], rationale=f"Not applicable: {reason}")


class Unavailable(Exception):  # noqa: N818 (domain term)
    """The evaluator could not run (provider failure, timeout); the runner retries once."""


@dataclass(frozen=True)
class SettingsField:
    key: str
    label: str
    type: Literal["select", "number", "int", "bool", "text", "text_long"]
    default: Any
    min: float | None = None
    max: float | None = None
    step: float | None = None
    options: tuple[str, ...] | None = None
    options_source: Literal["judge_models"] | None = None
    helper: str | None = None

    def as_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {"key": self.key, "label": self.label, "type": self.type, "default": self.default}
        for name in ("min", "max", "step", "options_source", "helper"):
            value = getattr(self, name)
            if value is not None:
                out[name] = value
        if self.options is not None:
            out["options"] = list(self.options)
        return out


def judge_model_field() -> SettingsField:
    return SettingsField(
        "judge_model",
        "Judge model",
        "select",
        None,  # filled with the platform default when served
        options_source="judge_models",
        helper="The model that reads the call and gives the verdict. Default: {default}.",
    )


class Evaluator:
    """Base of every built-in and custom evaluator. Class attributes declare the catalog row."""

    name: ClassVar[str]
    display_name: ClassVar[str]
    description: ClassVar[str]
    scope: ClassVar[Scope] = "call"
    cost_class: ClassVar[CostClass] = "free"
    output_kind: ClassVar[OutputKind] = "class"
    agent_types: ClassVar[tuple[AgentType, ...]] = ALL_AGENT_TYPES
    enabled_by_default: ClassVar[bool] = False
    VERSION: ClassVar[int] = 1
    score_range: ClassVar[tuple[float, float]] = (0.0, 1.0)
    settings_fields: ClassVar[tuple[SettingsField, ...]] = ()
    # Higher score is worse (anomaly distance); calibration sweeps thresholds the other way.
    threshold_direction: ClassVar[Literal["below_fails", "above_fails"]] = "below_fails"
    rules: ClassVar[str] = ""  # what the version pins (prompt text or rule summary)

    def max_failed_items(self, settings: Mapping[str, Any]) -> int:
        return int(settings.get("max_failed_items", 0) or 0)

    async def evaluate(self, ctx: EvalContext, settings: Mapping[str, Any], tools: EvalTools) -> EvalOutcome:
        raise NotImplementedError


@dataclass
class EvalTools:
    """Runtime helpers handed to ``evaluate``: the judge, the recording reader and the
    neighbour search. Each is optional so unit tests pass only what they need."""

    judge: Any = None  # app.evaluators.judge.Judge
    read_levels: Callable[[RecordingRef], Awaitable[Any]] | None = None
    neighbours: Callable[[EvalContext, Mapping[str, Any]], Awaitable[Any]] | None = None
    judge_model: str | None = None
    cutoff: float = 0.5


def quote(text: str, limit: int = 140) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 3].rstrip() + "..."


def turn_label(message: Message) -> str:
    return f"turn {message.index}"


def first_n(values: Sequence[str], n: int = 3) -> str:
    return ", ".join(values[:n]) + (f" and {len(values) - n} more" if len(values) > n else "")
