"""Language models for text simulations, and the offline fallback (008 research R1, R4, R6).

Three roles use a model in a simulation:

- ``agent``: the agent under test (the snapshot's LLM, and a flow node's own LLM);
- ``caller``: the simulated caller in persona mode (``settings.persona_model``);
- ``synth``: the short JSON stand-in for an HTTP tool without a mock (the agent's LLM).

Every model is built through the worker's adapter registry from a ``provider/model`` choice, so
no vendor is named here (Principle I). When the worker holds no key for the provider (the
offline harness, a deployment without that vendor), :func:`default_factory` returns a
:class:`ScriptLLM` running one of the deterministic offline scripts below instead. This module
is the only place that fallback lives.

:class:`TokenMeter` sums token usage per role from each model's ``metrics_collected`` events,
in the ``usage`` shape the API prices: ``{"agent": {"model": "<provider>/<model>",
"input_tokens": n, "output_tokens": n}, "caller": {...}, "synth": {...}}``. Rows produced by
the offline fallback carry ``"offline": true``.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal, Protocol

from worker.adapters.registry import AdapterRegistry, VendorSpec

if TYPE_CHECKING:
    from worker.settings import WorkerSettings

Role = Literal["agent", "caller", "synth"]


# Requests and replies of a scripted model


@dataclass(frozen=True)
class ScriptRequest:
    """What a scripted model sees: the chat items, the tools offered and the tool choice."""

    items: Sequence[Any]
    tools: Mapping[str, Mapping[str, Any]]  # name -> parameters schema
    tool_choice: Any = None

    def messages(self) -> list[tuple[str, str]]:
        out: list[tuple[str, str]] = []
        for item in self.items:
            if getattr(item, "type", None) != "message":
                continue
            out.append((str(getattr(item, "role", "")), str(item.text_content or "")))
        return out

    def last(self, role: str) -> str | None:
        for item_role, text in reversed(self.messages()):
            if item_role == role:
                return text
        return None

    def count(self, role: str) -> int:
        return sum(1 for item_role, _ in self.messages() if item_role == role)

    @property
    def after_tool_output(self) -> bool:
        return bool(self.items) and getattr(self.items[-1], "type", "") == "function_call_output"

    @property
    def forced(self) -> bool:
        return bool(self.tool_choice == "required")


@dataclass(frozen=True)
class ScriptReply:
    text: str = ""
    tool_calls: tuple[tuple[str, Mapping[str, Any]], ...] = ()


Script = Callable[[ScriptRequest], ScriptReply]


def _tool_parameters(tool: Any) -> tuple[str, Mapping[str, Any]]:
    info = getattr(tool, "info", None)
    raw = getattr(info, "raw_schema", None)
    if isinstance(raw, Mapping):
        return str(raw.get("name") or getattr(tool, "id", "")), dict(raw.get("parameters") or {})
    return str(getattr(tool, "id", "") or getattr(info, "name", "")), {}


def make_script_llm(
    script: Script, *, provider: str = "offline", model: str = "offline", offline: bool = False
) -> Any:
    """A livekit ``llm.LLM`` whose replies come from ``script`` (no network). Usage is estimated
    at four characters per token, so metering works the same as with a real model."""
    from livekit.agents import llm
    from livekit.agents.types import DEFAULT_API_CONNECT_OPTIONS, APIConnectOptions

    class ScriptStream(llm.LLMStream):
        def __init__(self, owner: Any, *, tool_choice: Any, **kwargs: Any) -> None:
            super().__init__(owner, **kwargs)
            self._choice = tool_choice

        async def _run(self) -> None:
            tools = dict(_tool_parameters(t) for t in self._tools)
            request = ScriptRequest(list(self._chat_ctx.items), tools, self._choice)
            reply = script(request)
            prompt_chars = sum(len(text) for _, text in request.messages())
            calls = [
                llm.FunctionToolCall(
                    name=name,
                    arguments=json.dumps(dict(args)),
                    call_id=f"call_{i}_{name}",
                )
                for i, (name, args) in enumerate(reply.tool_calls)
            ]
            if reply.text or calls:
                self._event_ch.send_nowait(
                    llm.ChatChunk(
                        id="script",
                        delta=llm.ChoiceDelta(
                            role="assistant", content=reply.text or None, tool_calls=calls
                        ),
                    )
                )
            out_chars = len(reply.text) + sum(len(c.arguments) for c in calls)
            prompt_tokens = max(1, prompt_chars // 4)
            completion_tokens = max(1, out_chars // 4)
            self._event_ch.send_nowait(
                llm.ChatChunk(
                    id="script",
                    usage=llm.CompletionUsage(
                        completion_tokens=completion_tokens,
                        prompt_tokens=prompt_tokens,
                        total_tokens=prompt_tokens + completion_tokens,
                    ),
                )
            )

    class ScriptLLM(llm.LLM):  # type: ignore[type-arg]
        def __init__(self) -> None:
            super().__init__()
            self.offline = offline
            self.requests: list[ScriptRequest] = []

        @property
        def model(self) -> str:
            return model

        @property
        def provider(self) -> str:
            return provider

        def prewarm(self, **_: Any) -> None:
            return None

        def chat(
            self,
            *,
            chat_ctx: Any,
            tools: list[Any] | None = None,
            conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS,
            tool_choice: Any = None,
            **_: Any,
        ) -> Any:
            stream = ScriptStream(
                self,
                tool_choice=tool_choice,
                chat_ctx=chat_ctx,
                tools=tools or [],
                conn_options=conn_options,
            )
            self.requests.append(
                ScriptRequest(
                    list(chat_ctx.items),
                    dict(_tool_parameters(t) for t in tools or []),
                    tool_choice,
                )
            )
            return stream

    return ScriptLLM()


# Offline scripts (deterministic; used only when the worker has no key for the provider)

OFFLINE_GREETING = "Hello, thanks for calling. How can I help you today?"
OFFLINE_CALLER_DONE = "That is everything I needed."
OFFLINE_SYNTH = {"status": "ok", "note": "offline stand-in"}


def _minimal_arguments(schema: Mapping[str, Any]) -> dict[str, Any]:
    """The smallest arguments that satisfy a forced call: the first enum value of each
    required property, else an empty value of its type."""
    props = schema.get("properties") or {}
    out: dict[str, Any] = {}
    for name in schema.get("required") or []:
        sub = props.get(name) or {}
        if sub.get("enum"):
            out[name] = sub["enum"][0]
        else:
            kind = sub.get("type")
            out[name] = {
                "integer": 0,
                "number": 0,
                "boolean": False,
                "array": [],
                "object": {},
            }.get(str(kind), "")
    return out


def offline_agent(request: ScriptRequest) -> ScriptReply:
    """The agent: a fixed opening, then an acknowledgement of what the caller said. Forced
    calls (a flow's classify or extract) get the first allowed value."""
    if request.forced and request.tools:
        name, schema = next(iter(request.tools.items()))
        return ScriptReply(tool_calls=((name, _minimal_arguments(schema)),))
    said = request.last("user")
    if said is None:
        return ScriptReply(OFFLINE_GREETING)
    said = " ".join(said.split())[:200]
    return ScriptReply(f"Thanks, I understand: {said}. Is there anything else I can help with?")


def offline_caller(brief: Mapping[str, Any] | None) -> Script:
    """The simulated caller: the opening line (or the goal), then one known fact per turn, then
    ``hang_up``. The caller's own earlier lines are the ``assistant`` messages of its chat."""
    brief = dict(brief or {})
    first = str(brief.get("opening_line") or "").strip() or str(brief.get("goal") or "").strip()
    lines = [line for line in [first, *(str(f) for f in brief.get("known_facts") or [])] if line]

    def script(request: ScriptRequest) -> ScriptReply:
        spoken = request.count("assistant")
        if spoken < len(lines):
            return ScriptReply(lines[spoken])
        if "hang_up" in request.tools:
            return ScriptReply(tool_calls=(("hang_up", {"reason": "goal reached"}),))
        return ScriptReply(OFFLINE_CALLER_DONE)

    return script


def offline_synth(request: ScriptRequest) -> ScriptReply:
    return ScriptReply(json.dumps(OFFLINE_SYNTH, separators=(",", ":")))


# Factory


class ModelFactory(Protocol):
    def __call__(
        self, spec: VendorSpec, role: Role, context: Mapping[str, Any] | None = None
    ) -> Any:
        """A livekit ``llm.LLM`` for ``spec`` in ``role``; ``context`` is the persona brief for
        the caller (only the offline caller script reads it)."""
        ...


def parse_model(value: str | None, default: VendorSpec) -> VendorSpec:
    """``provider/model`` (for example a persona model setting) to an LLM spec."""
    text = str(value or "").strip()
    if not text:
        return default
    provider, _, model = text.partition("/")
    if not model:
        return VendorSpec("llm", default.provider, provider, {})
    return VendorSpec("llm", provider, model, {})


def has_credentials(creds: Mapping[str, str]) -> bool:
    """True when the provider's credentials hold a key (any non-empty ``*api_key`` value)."""
    return any(value for key, value in creds.items() if key.endswith("api_key"))


def offline_model(spec: VendorSpec, role: Role, context: Mapping[str, Any] | None = None) -> Any:
    script: Script
    if role == "caller":
        script = offline_caller(context)
    elif role == "synth":
        script = offline_synth
    else:
        script = offline_agent
    return make_script_llm(script, provider=spec.provider, model=spec.model or "", offline=True)


def default_factory(
    registry: AdapterRegistry, credentials: Mapping[str, Mapping[str, str]]
) -> ModelFactory:
    """Real adapters when the worker holds a key for the provider, else the offline scripts."""

    def build(spec: VendorSpec, role: Role, context: Mapping[str, Any] | None = None) -> Any:
        spec = registry.check(spec)
        creds = credentials.get(spec.provider, {})
        if not has_credentials(creds):
            return offline_model(spec, role, context)
        return registry.build(spec, creds)

    return build


def settings_factory(settings: WorkerSettings, registry: AdapterRegistry) -> ModelFactory:
    return default_factory(registry, settings.vendor_credentials())


# Metering and one-shot completions


@dataclass
class TokenMeter:
    rows: dict[str, dict[str, Any]] = field(default_factory=dict)
    cached: dict[str, int] = field(default_factory=dict)

    def attach(self, llm: Any, role: Role, spec: VendorSpec) -> Any:
        """Count every completion of ``llm`` under ``role`` (first model seen names the row)."""
        label = f"{spec.provider}/{spec.model}"
        offline = bool(getattr(llm, "offline", False))
        on = getattr(llm, "on", None)
        if not callable(on):
            return llm

        def collect(metrics: Any) -> None:
            if getattr(metrics, "type", None) != "llm_metrics":
                return
            self.add(
                role,
                label,
                input_tokens=int(metrics.prompt_tokens or 0),
                cached_input_tokens=int(metrics.prompt_cached_tokens or 0),
                output_tokens=int(metrics.completion_tokens or 0),
                offline=offline,
            )

        on("metrics_collected", collect)
        return llm

    def add(
        self,
        role: Role,
        model: str,
        *,
        input_tokens: int,
        output_tokens: int,
        cached_input_tokens: int = 0,
        offline: bool = False,
    ) -> None:
        row = self.rows.setdefault(role, {"model": model, "input_tokens": 0, "output_tokens": 0})
        row["input_tokens"] += max(0, input_tokens)
        row["output_tokens"] += max(0, output_tokens)
        self.cached[role] = self.cached.get(role, 0) + max(0, cached_input_tokens)
        if offline:
            row["offline"] = True

    def usage(self) -> dict[str, dict[str, Any]]:
        return {role: dict(row) for role, row in self.rows.items()}


@dataclass(frozen=True)
class Completion:
    text: str
    tool_calls: list[tuple[str, dict[str, Any]]]


async def complete(
    llm: Any, system: str, messages: Sequence[tuple[str, str]], tools: Sequence[Any] = ()
) -> Completion:
    """One model call outside a session: ``messages`` are ``(role, text)`` with role ``user``
    or ``assistant``. Returns the text and any tool calls with parsed arguments."""
    from livekit.agents import llm as lk_llm

    ctx = lk_llm.ChatContext.empty()
    ctx.add_message(role="system", content=system)
    for role, text in messages:
        ctx.add_message(role="assistant" if role == "assistant" else "user", content=text)
    stream = llm.chat(chat_ctx=ctx, tools=list(tools)) if tools else llm.chat(chat_ctx=ctx)
    text = ""
    calls: dict[str, tuple[str, str]] = {}
    async with stream:
        async for chunk in stream:
            delta = getattr(chunk, "delta", None)
            if delta is None:
                continue
            text += getattr(delta, "content", None) or ""
            for call in getattr(delta, "tool_calls", None) or []:
                key = call.call_id or call.name
                name, args = calls.get(key, (call.name, ""))
                calls[key] = (name, args + (call.arguments or ""))
    parsed: list[tuple[str, dict[str, Any]]] = []
    for name, raw in calls.values():
        try:
            value = json.loads(raw) if raw else {}
        except ValueError:
            value = {}
        parsed.append((name, value if isinstance(value, dict) else {}))
    return Completion(text.strip(), parsed)
