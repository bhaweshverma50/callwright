"""Tool shapes (contracts/tools.yaml, data-model.md section 1; T008, T094).

Every config model forbids unknown keys, so only one shape is ever stored and an outdated field
(a legacy transfer block next to the current one) is rejected naming the field (FR-045).

``HttpRequestSpec`` and ``TransferSpec`` are shared with 004: webhook nodes and transfer nodes
validate with the same models, so the tool form and the node form accept the same values.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Annotated, Any, Literal

from callwright_contract.http_core import DEFAULT_TIMEOUT_MS
from callwright_contract.values import DEFAULT_EXECUTION_MESSAGE, E164_PATTERN, KB_TOOL
from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic_core import to_jsonable_python

from app.agents.schemas import MAX_TOOLS

# Function names the flow compiler gives transitions (004); a tool may not take one.
ROUTE_TOOL_PREFIX = "route_to_"
DEFAULT_HOLD_MESSAGE = "Please hold while I connect you."

ToolType = Literal["end_call", "transfer_call", "press_digit", "http"]
HttpMethod = Literal["GET", "POST", "PUT", "PATCH", "DELETE"]

NAME_PATTERN = r"^[a-z][a-z0-9_]{0,63}$"
HEADER_NAME_PATTERN = r"^[!#$%&'*+.^_`|~0-9A-Za-z-]{1,128}$"
RESERVED_NAMES = frozenset({KB_TOOL})
RESERVED_PREFIXES = (ROUTE_TOOL_PREFIX,)

ToolName = Annotated[str, Field(pattern=NAME_PATTERN)]
E164 = Annotated[str, Field(pattern=E164_PATTERN)]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EndCallConfig(_Strict):
    message: str | None = Field(default=None, max_length=500)


class WarmTransfer(_Strict):
    handoff_type: Literal["private", "public"]
    briefing_message_type: Literal["static", "prompt"]
    briefing_message: str = Field(max_length=1000)


class TransferSpec(_Strict):
    routing_type: Literal["static", "dynamic"] = "static"
    number: E164 | None = None
    routing_instructions: str | None = Field(default=None, max_length=2000)
    allowed_numbers: list[E164] = Field(default_factory=list, max_length=50)
    transfer_type: Literal["cold", "warm"] = "cold"
    warm_transfer: WarmTransfer | None = None
    hold_message: str = Field(default=DEFAULT_HOLD_MESSAGE, max_length=500)
    ring_timeout_s: int = Field(default=30, ge=5, le=120)

    @model_validator(mode="after")
    def _required_by_mode(self) -> TransferSpec:
        if self.routing_type == "static" and not self.number:
            raise ValueError("number: Enter the phone number to transfer to, in +E.164 form.")
        if self.routing_type == "dynamic" and not (self.routing_instructions or "").strip():
            raise ValueError("routing_instructions: Describe how the agent picks the number.")
        if self.transfer_type == "warm" and self.warm_transfer is None:
            raise ValueError("warm_transfer: A warm transfer needs a handoff type and a briefing.")
        return self


class PressDigitConfig(_Strict):
    delay_ms: int = Field(default=1000, ge=0, le=10000)
    cooldown_ms: int = Field(default=5000, ge=0, le=60000)


class HeaderSpec(_Strict):
    name: str = Field(pattern=HEADER_NAME_PATTERN)
    value: str | None = Field(default=None, max_length=4096)
    secret: bool = False
    # Read-only on the wire; accepted (and ignored except for matching) when a client sends back
    # what it read.
    secret_ref: str | None = None
    masked_value: str | None = None


class ResponseMapping(_Strict):
    variable_name: str = Field(pattern=NAME_PATTERN)
    json_path: str = Field(min_length=1, max_length=256)


def _default_headers() -> list[HeaderSpec]:
    return [HeaderSpec(name="Content-Type", value="application/json", secret=False)]


class HttpRequestSpec(_Strict):
    method: HttpMethod = "POST"
    url: str = Field(min_length=1, max_length=2048)
    headers: list[HeaderSpec] = Field(default_factory=_default_headers, max_length=20)
    body_template: Any = None
    timeout_ms: int = Field(default=DEFAULT_TIMEOUT_MS, ge=1000, le=30000)
    response_mappings: list[ResponseMapping] = Field(default_factory=list, max_length=20)
    speak_during_execution: bool = True
    execution_message: str = Field(default=DEFAULT_EXECUTION_MESSAGE, max_length=300)


def _default_parameters() -> dict[str, Any]:
    return {"type": "object", "properties": {}, "required": []}


class HttpToolConfig(HttpRequestSpec):
    parameters: dict[str, Any] = Field(default_factory=_default_parameters)


CONFIG_MODELS: dict[str, type[BaseModel]] = {
    "end_call": EndCallConfig,
    "transfer_call": TransferSpec,
    "press_digit": PressDigitConfig,
    "http": HttpToolConfig,
}


def config_defaults(model: type[BaseModel]) -> dict[str, Any]:
    """Every optional field of ``model`` at its default, in JSON form."""
    return {
        name: to_jsonable_python(f.get_default(call_default_factory=True), exclude_none=True)
        for name, f in model.model_fields.items()
        if not f.is_required()
    }


def with_config_defaults(tool_type: str, config: Mapping[str, Any]) -> dict[str, Any]:
    """``config`` with every field it leaves out at the schema's default: what a version
    snapshot carries, so the worker reads each value as given."""
    model = CONFIG_MODELS.get(tool_type)
    return {**(config_defaults(model) if model else {}), **config}


class ToolCreate(_Strict):
    type: ToolType
    name: str = Field(max_length=64)
    description: str = Field(min_length=1, max_length=1000)
    config: dict[str, Any] = Field(default_factory=dict)
    mock_response: str | None = Field(default=None, max_length=16384)


class ToolUpdate(_Strict):
    name: str | None = Field(default=None, max_length=64)
    description: str | None = Field(default=None, min_length=1, max_length=1000)
    config: dict[str, Any] | None = None
    mock_response: str | None = Field(default=None, max_length=16384)


class ToolSpec(BaseModel):
    """Snapshot form stored in AgentVersion ``tools`` (secret headers carry only ``secret_ref``)."""

    tool_id: str
    type: ToolType
    name: str
    description: str
    config: dict[str, Any]
    mock_response: str | None = None


class SetAgentTools(_Strict):
    tool_ids: list[Annotated[str, Field(pattern=r"^tool_")]] = Field(max_length=MAX_TOOLS)


class TestRunRequest(_Strict):
    tool_id: str | None = Field(default=None, pattern=r"^tool_")
    tool: ToolCreate | None = None
    arguments: dict[str, Any] = Field(default_factory=dict)
    dynamic_variables: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _one_source(self) -> TestRunRequest:
        if (self.tool_id is None) == (self.tool is None):
            raise ValueError("Send either tool_id or tool.")
        return self
