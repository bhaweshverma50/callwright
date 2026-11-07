"""The text runner protocol (008): the arq queue the voice worker's ``textsim`` role consumes and
its two jobs, the run specs the API hands the runner (``GET /v1/internal/test-runs/{trn}/cases/
{tc}/spec``, ``GET /v1/internal/simulation-runs/{srun}/spec``) and the results it posts back
(``POST .../result``), as in ``specs/008-testing-simulation/contracts``."""

from __future__ import annotations

from typing import Any, Final, Literal, get_args

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from callwright_contract.calls import AgentType, Channel
from callwright_contract.protocol import RuntimeValues

TEXTSIM_QUEUE: Final = "arq:textsim"
RUN_SINGLE_TURN: Final = "run_single_turn"
RUN_SIMULATION: Final = "run_simulation"

SimulationEndReason = Literal[
    "caller_turns_exhausted",
    "caller_hung_up",
    "agent_hangup",
    "call_transfer",
    "turn_limit_reached",
    "error",
]
SimMode = Literal["replay", "persona"]
# How a simulated HTTP tool or webhook node was answered (null for tools that run for real).
AnswerSource = Literal["mock", "recorded", "synthesized", "error"]
ANSWER_SOURCES: Final[tuple[AnswerSource, ...]] = get_args(AnswerSource)

# Caller turns of a persona run, and agent replies of a replay before ``turn_limit_reached``.
DEFAULT_CALLER_TURNS: Final = 20
MAX_CALLER_TURNS: Final = 50
MAX_ERROR_CHARS: Final = 2000


def _string_map(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {str(k): "" if v is None else str(v) for k, v in value.items()}


class SimSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_caller_turns: int = Field(default=DEFAULT_CALLER_TURNS, ge=1, le=MAX_CALLER_TURNS)
    missing_mock_policy: Literal["synthesize", "error"] = "synthesize"
    persona_model: str | None = None


class PersonaBrief(BaseModel):
    """Who a persona caller plays (research R6): written by the user or extracted from a call."""

    model_config = ConfigDict(extra="forbid")

    goal: str = Field(min_length=1, max_length=1000)
    known_facts: list[str] = Field(default_factory=list, max_length=30)
    temperament: str = Field(default="", max_length=300)
    speaking_style: str = Field(default="", max_length=300)
    constraints: list[str] = Field(default_factory=list, max_length=20)
    opening_line: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def _items(self) -> PersonaBrief:
        for name in ("known_facts", "constraints"):
            if any(len(v) > 300 for v in getattr(self, name)):
                raise ValueError(f"each {name} entry is at most 300 characters")
        return self


class RecordedOutput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str
    output: str


class CaseSpec(BaseModel):
    """One single-turn test case (``internalGetTestCaseSpec``)."""

    model_config = ConfigDict(extra="ignore")

    workspace_id: str
    agent_id: str
    agent_type: AgentType
    runtime: RuntimeValues
    user_prompt: str
    dynamic_variables: dict[str, str] = Field(default_factory=dict)

    @field_validator("dynamic_variables", mode="before")
    @classmethod
    def _vars(cls, value: Any) -> dict[str, str]:
        return _string_map(value)


class SimulationSpec(BaseModel):
    """One simulation run (``internalGetSimulationSpec``)."""

    model_config = ConfigDict(extra="ignore")

    workspace_id: str
    simulation_run_id: str
    output_call_id: str
    agent_id: str
    agent_type: AgentType
    channel: Channel
    mode: SimMode
    runtime: RuntimeValues
    settings: SimSettings = Field(default_factory=SimSettings)
    dynamic_variables: dict[str, str] = Field(default_factory=dict)
    # Replay only: who spoke first on the base call; the replay opens the same way.
    start_speaker: Literal["agent", "user"] | None = None
    caller_turns: list[str] = Field(default_factory=list)
    recorded_tool_outputs: list[RecordedOutput] = Field(default_factory=list)
    original_node_path: list[str] = Field(default_factory=list)
    persona_brief: PersonaBrief | None = None

    @field_validator("dynamic_variables", mode="before")
    @classmethod
    def _vars(cls, value: Any) -> dict[str, str]:
        return _string_map(value)


class UsageRow(BaseModel):
    """Tokens one role of a text run used (``agent``, ``caller``, ``synth``); ``model`` is
    ``provider/model``."""

    model_config = ConfigDict(extra="ignore")

    model: str | None = None
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    # The worker ran this role on its offline script (no vendor key): nothing to charge.
    offline: bool = False


class ToolCallRecord(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    output: str | None = None
    answer_source: AnswerSource | None = None


class CaseResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    status: Literal["completed", "error"]
    agent_response: str | None = None
    tool_calls: list[ToolCallRecord] = Field(default_factory=list)
    nodes_visited: list[str] = Field(default_factory=list)
    usage: dict[str, UsageRow] = Field(default_factory=dict)
    duration_ms: int | None = None
    error_message: str | None = None


class SimResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    status: Literal["completed", "failed"]
    end_reason: SimulationEndReason | None = None
    diverged_at_turn: int | None = None
    answer_source_counts: dict[AnswerSource, int] = Field(default_factory=dict)
    persona_brief: PersonaBrief | None = None
    usage: dict[str, UsageRow] = Field(default_factory=dict)
    error_message: str | None = None
