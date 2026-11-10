"""Request bodies and fix payloads (009 T008; contracts/issues.yaml).

``FixPayload`` is a union discriminated by the fix kind, which the request carries next to the
payload (``{kind, payload}``): ``payload_model(kind)`` returns the model for one kind and
``parse_payload(kind, raw)`` validates a raw payload into its canonical dict.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

FixKind = Literal[
    "prompt_edit",
    "node_prompt_edit",
    "add_guardrail",
    "tool_description_edit",
    "transition_condition_edit",
    "add_transition",
    "node_tool_attachment",
    "kb_attach",
]
FIX_KINDS: tuple[FixKind, ...] = (
    "prompt_edit",
    "node_prompt_edit",
    "add_guardrail",
    "tool_description_edit",
    "transition_condition_edit",
    "add_transition",
    "node_tool_attachment",
    "kb_attach",
)
DismissReason = Literal["not_a_problem", "evaluator_wrong", "wont_fix", "duplicate", "other"]
ToolId = Annotated[str, Field(pattern=r"^tool_")]
KbId = Annotated[str, Field(pattern=r"^kb_")]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _Payload(BaseModel):
    model_config = ConfigDict(extra="ignore")


class PromptEdit(_Payload):
    current_prompt: str
    proposed_prompt: str = Field(min_length=1, max_length=20000)


class NodePromptEdit(_Payload):
    node_id: str = Field(min_length=1)
    node_label: str | None = None
    current_instructions: str
    proposed_instructions: str = Field(min_length=1, max_length=8000)


class AddGuardrail(_Payload):
    placement: Literal["agent_prompt", "node", "all_agent_nodes"]
    node_id: str | None = None
    rule_text: str = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def _node(self) -> AddGuardrail:
        if self.placement == "node" and not self.node_id:
            raise ValueError("Choose the node the rule goes to.")
        return self


class ToolDescriptionEdit(_Payload):
    tool_id: ToolId
    tool_name: str | None = None
    current_description: str
    proposed_description: str = Field(min_length=1, max_length=1000)


class TransitionConditionEdit(_Payload):
    edge_id: str = Field(min_length=1)
    edge_label: str | None = None
    source_node_id: str | None = None
    current_condition: str
    proposed_condition: str = Field(min_length=1, max_length=1000)


class AddTransition(_Payload):
    source_node_id: str = Field(min_length=1)
    target_node_id: str = Field(min_length=1)
    edge_label: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    handoff_condition: str = Field(min_length=1, max_length=1000)


class NodeToolAttachment(_Payload):
    node_id: str = Field(min_length=1)
    tools_to_attach: list[ToolId] = Field(default_factory=list, max_length=25)
    tools_to_detach: list[ToolId] = Field(default_factory=list, max_length=25)

    @model_validator(mode="after")
    def _one(self) -> NodeToolAttachment:
        if not self.tools_to_attach and not self.tools_to_detach:
            raise ValueError("Attach or detach at least one tool.")
        return self


class KbAttach(_Payload):
    kb_ids_to_attach: list[KbId] = Field(default_factory=list, max_length=20)
    uncovered_topics: list[Annotated[str, Field(max_length=200)]] = Field(default_factory=list, max_length=20)


PAYLOAD_MODELS: dict[str, type[_Payload]] = {
    "prompt_edit": PromptEdit,
    "node_prompt_edit": NodePromptEdit,
    "add_guardrail": AddGuardrail,
    "tool_description_edit": ToolDescriptionEdit,
    "transition_condition_edit": TransitionConditionEdit,
    "add_transition": AddTransition,
    "node_tool_attachment": NodeToolAttachment,
    "kb_attach": KbAttach,
}


def payload_model(kind: str) -> type[_Payload]:
    return PAYLOAD_MODELS[kind]


def parse_payload(kind: str, raw: Any) -> dict[str, Any]:
    """The payload as a canonical dict (raises ``pydantic.ValidationError``)."""
    model = payload_model(kind).model_validate(raw if isinstance(raw, dict) else {})
    return model.model_dump(mode="json", exclude_none=True)


__all__ = ["FIX_KINDS", "ValidationError", "parse_payload"]


class DetectBody(_Strict):
    agent_id: str = Field(pattern=r"^agt_")
    window_days: Literal[7, 14, 30, 90] = 14
    include_simulated: bool = False


class CreateFixBody(_Strict):
    mode: Literal["ai", "manual"]
    kind: FixKind | None = None
    guidance: str | None = Field(default=None, max_length=1000)
    payload: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _manual(self) -> CreateFixBody:
        if self.mode == "manual" and (self.kind is None or self.payload is None):
            raise ValueError("A manual fix needs a kind and a payload.")
        return self


class ValidationBody(_Strict):
    dry_run: bool = False
    mode: Literal["persona", "replay"] = "persona"
    affected_limit: int = Field(default=20, ge=3, le=20)
    guard_limit: int = Field(default=10, ge=0, le=10)
    min_improvement_pp: float = Field(default=10, ge=5, le=50)
    max_regression_pp: float = Field(default=5, ge=0, le=20)
    min_sample: int = Field(default=5, ge=3, le=50)


class DraftAndValidateBody(ValidationBody):
    kind: FixKind | None = None
    guidance: str | None = Field(default=None, max_length=1000)


class ApplyBody(_Strict):
    fix_revision: int | None = Field(default=None, ge=1)
    publish: bool = True
    release_notes_extra: str | None = Field(default=None, max_length=500)


class DismissBody(_Strict):
    reason: DismissReason
    note: str | None = Field(default=None, max_length=500)
    duplicate_of: str | None = Field(default=None, pattern=r"^iss_")
