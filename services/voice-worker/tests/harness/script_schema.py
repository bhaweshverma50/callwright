"""YAML script format for the scripted caller (research R20; see README.md).

A script is a list of steps run in order on a virtual clock. Action steps drive the caller or
the call; ``expect_*`` steps assert on what happened so far.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class VendorTiming(Strict):
    """Latency profile of one fake vendor. Values in milliseconds."""

    stt_final_ms: float | None = None
    llm_ttft_ms: float | None = None
    tts_ttfb_ms: float | None = None
    ms_per_char: float | None = None


class LlmRule(Strict):
    """FakeLLM rule: the first rule whose ``match`` occurs in the caller text wins."""

    match: str = ""
    reply: str = ""
    tool: str | None = None
    tool_arguments: dict[str, Any] = Field(default_factory=dict)
    tool_output: str | None = None
    tool_ms: float = 300.0
    transition: str | None = None
    end_call: bool = False


class Fakes(Strict):
    stt_final_ms: float = 150.0
    llm_ttft_ms: float = 280.0
    tts_ttfb_ms: float = 120.0
    ms_per_char: float = 55.0
    preemptive_generation: bool = True
    vendors: dict[str, VendorTiming] = Field(
        default_factory=dict,
        description="Per vendor, keyed 'kind/provider' or 'kind/provider/model'",
    )
    default_reply: str = "Sure, I can help with that."
    greeting_reply: str = "Hello, how can I help you today?"
    rules: list[LlmRule] = Field(default_factory=list)


class ApiBehaviour(Strict):
    """Fake internal API: return ``control.end_call`` on the given post (1-based)."""

    end_call_on_post: int | None = None
    end_call_reason: Literal["insufficient_credit", "error"] = "insufficient_credit"


class Step(Strict):
    # caller actions
    say: str | None = None
    duration_ms: float | None = None
    pause_ms: float = 500.0
    segment_pause_ms: float = 800.0  # silence between the "a | b" parts of one turn
    interrupt_after_ms: float | None = None
    silence_s: float | None = None
    dtmf: str | None = None
    digit_interval_ms: float = 300.0
    machine_greeting: str | None = None
    hangup: bool | None = None
    override: dict[str, Any] | None = None
    wait_idle: bool | None = None
    # expectations
    expect_agent_says: str | None = None
    expect_agent_speaks: str | None = None
    expect_user_says: str | None = None
    expect_tool: str | None = None
    expect_transition: str | None = None
    expect_end_reason: str | None = None
    expect_within_ms: float | None = None
    expect_interrupted: bool | None = None
    expect_event: dict[str, Any] | None = None
    expect_no_event: dict[str, Any] | None = None
    expect_meter: dict[str, Any] | None = None
    expect_background: dict[str, Any] | None = None
    expect_turns: int | None = None
    expect_cutoffs: int | None = None  # turns committed in a mid-sentence pause so far


class Script(Strict):
    name: str
    description: str = ""
    config_file: str | None = None
    config: dict[str, Any] = Field(default_factory=dict)
    runtime: dict[str, Any] = Field(default_factory=dict)
    fakes: Fakes = Field(default_factory=Fakes)
    api: ApiBehaviour = Field(default_factory=ApiBehaviour)
    steps: list[Step]


def load_script(path: str | Path) -> Script:
    raw = yaml.safe_load(Path(path).read_text())
    return Script.model_validate(raw)
