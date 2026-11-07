"""Flow test support (004): a rule-driven fake LLM for the real ``AgentSession`` in text mode, a
recording call control, and a scripted-caller runner for the flow scenarios.

The fake LLM answers like a model would: when the caller's last message matches a rule it
calls that rule's tool (a transition, ``complete_task`` or a lookup); the forced silent calls of
the runtime (``choose_category``, ``save_values``) get their answer from the scenario; anything
else gets a short text reply.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from callwright_contract.protocol import RuntimeConfig

from tests.harness.runner import build_runtime
from worker.adapters.registry import AdapterRegistry
from worker.flow.runtime import CallwrightFlowRunner
from worker.pipeline import plan_session
from worker.tools import OverrideResult, SegmentOverrides, ToolActivity
from worker.tools.registry import build_call_tools

FLOWS = Path(__file__).parent / "harness" / "flows"
SCENARIOS = Path(__file__).parent / "harness" / "scenarios"


def compiled_config(name: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((FLOWS / f"{name}.compiled.json").read_text())
    config: dict[str, Any] = data["config"]
    return config


@dataclass
class Rule:
    match: str
    tool: str | None = None
    args: dict[str, Any] = field(default_factory=dict)
    reply: str | None = None


@dataclass
class FlowScript:
    rules: list[Rule] = field(default_factory=list)
    classify: dict[str, str] = field(default_factory=dict)  # caller text fragment -> category
    extract: dict[str, dict[str, Any]] = field(default_factory=dict)  # fragment -> values
    default_reply: str = "Sure, I can help with that."
    llm_delay_s: float = 0.0
    # What the model writes when an End node asks it for the goodbye ("" answers nothing,
    # None fails the request).
    goodbye: str | None = "Glad I could help. Goodbye!"
    goodbye_delay_s: float = 0.0


def flow_llm(script: FlowScript, model: str = "gpt-5.1") -> Any:
    from livekit.agents import llm
    from livekit.agents.types import DEFAULT_API_CONNECT_OPTIONS, APIConnectOptions

    def last_user(chat_ctx: Any) -> str:
        for item in reversed(chat_ctx.items):
            if getattr(item, "role", None) == "user":
                return str(item.text_content or "")
        return ""

    def transcript(chat_ctx: Any) -> str:
        return " ".join(str(getattr(i, "text_content", "") or "") for i in chat_ctx.items).lower()

    class Stream(llm.LLMStream):
        def __init__(
            self, owner: Any, *, chat_ctx: Any, tools: list[Any], conn_options: Any
        ) -> None:
            super().__init__(owner, chat_ctx=chat_ctx, tools=tools, conn_options=conn_options)
            self.owner = owner

        async def _run(self) -> None:
            if script.llm_delay_s:
                await asyncio.sleep(script.llm_delay_s)
            names = {getattr(t, "id", None) or getattr(t, "name", None) for t in self._tools}
            first = self._chat_ctx.items[0] if self._chat_ctx.items else None
            if not names and "call is ending now" in str(getattr(first, "text_content", "")):
                self.owner.goodbyes.append(self._chat_ctx.copy())
                if script.goodbye_delay_s:
                    await asyncio.sleep(script.goodbye_delay_s)
                if script.goodbye is None:
                    raise RuntimeError("model unavailable")
                if script.goodbye:
                    self._text(script.goodbye)
                return
            text = transcript(self._chat_ctx)
            call: tuple[str, dict[str, Any]] | None = None
            if "choose_category" in names:
                category = next(
                    (c for frag, c in script.classify.items() if frag.lower() in text), None
                )
                call = ("choose_category", {"category": category}) if category else None
            elif "save_values" in names:
                values = next((v for frag, v in script.extract.items() if frag.lower() in text), {})
                call = ("save_values", values)
            else:
                items = self._chat_ctx.items
                after_tool = (
                    bool(items) and getattr(items[-1], "type", "") == "function_call_output"
                )
                said = last_user(self._chat_ctx).lower()
                if not after_tool:
                    for rule in script.rules:
                        if rule.match.lower() in said and rule.tool and rule.tool in names:
                            call = (rule.tool, rule.args)
                            break
                        if rule.match.lower() in said and rule.reply and not rule.tool:
                            self._text(rule.reply)
                            return
            if call is not None:
                self.owner.calls.append(call[0])
                self._event_ch.send_nowait(
                    llm.ChatChunk(
                        id="fake",
                        delta=llm.ChoiceDelta(
                            role="assistant",
                            tool_calls=[
                                llm.FunctionToolCall(
                                    name=call[0],
                                    arguments=json.dumps(call[1]),
                                    call_id=f"c{len(self.owner.calls)}",
                                )
                            ],
                        ),
                    )
                )
                return
            self._text(script.default_reply)

        def _text(self, reply: str) -> None:
            self._event_ch.send_nowait(
                llm.ChatChunk(id="fake", delta=llm.ChoiceDelta(role="assistant", content=reply))
            )
            self._event_ch.send_nowait(
                llm.ChatChunk(
                    id="fake",
                    usage=llm.CompletionUsage(
                        completion_tokens=5, prompt_tokens=100, total_tokens=105
                    ),
                )
            )

    class FlowLLM(llm.LLM):  # type: ignore[type-arg]
        def __init__(self) -> None:
            super().__init__()
            self.requests: list[Any] = []
            self.calls: list[str] = []
            self.goodbyes: list[Any] = []

        @property
        def model(self) -> str:
            return model

        @property
        def provider(self) -> str:
            return "fake"

        def chat(
            self,
            *,
            chat_ctx: Any,
            tools: list[Any] | None = None,
            conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS,
            **_: Any,
        ) -> Any:
            self.requests.append((chat_ctx.copy(), [getattr(t, "id", None) for t in tools or []]))
            return Stream(self, chat_ctx=chat_ctx, tools=tools or [], conn_options=conn_options)

    return FlowLLM()


class RecordingControl:
    """``CallControl`` that records what the flow does."""

    def __init__(self, call_id: str = "call_01JA0FL0WTEST0000000000000") -> None:
        self._call_id = call_id
        self.transitions: list[dict[str, Any]] = []
        self.tools: list[ToolActivity] = []
        self.said: list[str] = []
        self.disconnect_reason: str | None = None
        self.diagnostic: str | None = None
        self.ended = asyncio.Event()

    @property
    def call_id(self) -> str:
        return self._call_id

    @property
    def room(self) -> Any:
        return None

    @property
    def ending(self) -> bool:
        return self.disconnect_reason is not None

    async def hang_up(self, reason: str, *, diagnostic: str | None = None) -> bool:
        if self.disconnect_reason is not None:
            return False
        self.disconnect_reason, self.diagnostic = reason, diagnostic
        self.ended.set()
        return True

    async def say(self, text: str, *, allow_interruptions: bool = True) -> None:
        self.said.append(text)

    async def send_dtmf(self, digits: str) -> None:
        return None

    def report_tool(self, activity: ToolActivity) -> None:
        self.tools.append(activity)

    def report_transition(
        self,
        to_node_id: str,
        *,
        from_node_id: str | None = None,
        label: str | None = None,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        self.transitions.append(
            {
                "from_node_id": from_node_id,
                "to_node_id": to_node_id,
                "label": label,
                **(details or {}),
            }
        )

    async def apply_overrides(self, overrides: SegmentOverrides) -> OverrideResult:
        return OverrideResult()

    @property
    def path(self) -> list[str]:
        if not self.transitions:
            return []
        return [str(self.transitions[0]["from_node_id"])] + [
            str(t["to_node_id"]) for t in self.transitions
        ]


@dataclass
class FlowCallResult:
    control: RecordingControl
    replies: list[str]
    llm: Any
    runtime: RuntimeConfig


async def run_flow_call(
    config: Mapping[str, Any],
    script: FlowScript,
    caller: list[str],
    *,
    runtime: Mapping[str, Any] | None = None,
    after_each: Any = None,
    control: RecordingControl | None = None,
) -> FlowCallResult:
    """A whole call on the real ``AgentSession`` in text mode: the opening as 003 plays it,
    then each caller line, until the flow hangs up or the lines run out."""
    from livekit.agents import AgentSession

    rt = build_runtime(dict(config), dict(runtime or {}))
    plan = plan_session(rt, AdapterRegistry())
    control = control or RecordingControl()
    tools = build_call_tools(rt, control)
    agent = CallwrightFlowRunner().build_agent(rt, control, [], plan=plan, base_tools=tools)
    model = flow_llm(script)
    replies: list[str] = []
    async with AgentSession(llm=model, vad=None) as session:
        await session.start(agent)
        if plan.start_speaker == "agent":
            if plan.greeting:
                await session.say(plan.greeting, allow_interruptions=False)
            else:
                await session.generate_reply()
        for line in caller:
            if control.ending:
                break
            result: Any = await session.run(user_input=line)
            replies += [
                e.item.text_content for e in result.events if getattr(e, "type", "") == "message"
            ]
            for _ in range(20):  # let handoffs and step agents settle
                await asyncio.sleep(0.01)
            if after_each is not None:
                after_each(control)
        for _ in range(20):
            await asyncio.sleep(0.01)
    await tools.aclose()
    return FlowCallResult(control, replies, model, rt)


def load_scenario(path: Path) -> dict[str, Any]:
    data: dict[str, Any] = yaml.safe_load(path.read_text())
    return data


def script_from(data: Mapping[str, Any]) -> FlowScript:
    llm = data.get("llm") or {}
    return FlowScript(
        rules=[Rule(**r) for r in llm.get("rules") or []],
        classify=dict(llm.get("classify") or {}),
        extract={k: dict(v) for k, v in (llm.get("extract") or {}).items()},
        default_reply=str(llm.get("default_reply") or "Sure, I can help with that."),
        **({"goodbye": llm["goodbye"]} if "goodbye" in llm else {}),
    )
