"""005's tool provider (T012, T029, T048, T079, T087, T100).

Builds the LLM function tools for a call from the version snapshot (``tools`` and
``knowledge``), dispatches every invocation through one path and reports it:

1. arguments are checked against the function's parameters (``invalid_arguments`` goes back to
   the LLM, nothing runs);
2. in a simulation (``RuntimeConfig.simulation``, set by 008 or the harness) HTTP tools answer
   their canned response (or 008's ``ToolContext.simulated_answer``) without network, transfer
   and press digit report fixed outcomes, and ``kb_search`` runs for real;
3. otherwise the executor for the type runs; lookup tools (HTTP and ``kb_search``) add a "still
   checking" line when they run longer than 3 s;
4. a ``tool_call`` event with timings, the outcome and secret-free arguments and output is
   recorded through the call control (in memory, posted by the event batcher: non-blocking).

Spoken fillers: :class:`FillerPolicy` tells the agent's ``llm_node`` which tools are lookups and
what to say at once when the model calls one before saying anything (pipeline.py). Internal
worker tools (voicemail detection) are not in the policy and never trigger a filler.

``kb_search`` is added when the snapshot lists knowledge bases. 004's flow executor passes
``kb_search_enabled=False`` for nodes that switch it off (``CallTools.function_tools``).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import re
import time
import weakref
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any

import httpx

from worker import telemetry
from worker.tools import (
    CallControl,
    ToolActivity,
    http_core,
    kb_search,
    register_tool_provider,
    secrets,
)
from worker.tools.base import ToolContext, ToolExecutor, ToolResult, ToolSpecView
from worker.tools.dtmf import PressDigitExecutor
from worker.tools.end_call import EndCallExecutor
from worker.tools.http import HttpExecutor
from worker.tools.transfer import TransferBackend, TransferExecutor

if TYPE_CHECKING:
    from worker.internal_api import RuntimeConfig
    from worker.settings import WorkerSettings

log = logging.getLogger(__name__)

FILLER_TEXT = "One moment, let me check that."
STILL_CHECKING = "Still checking, thanks for waiting."
STILL_CHECKING_AFTER_S = 3.0
# Said at once when the model ends the call without a goodbye of its own (it sometimes answers
# a caller's "thanks, that's all" with only the end_call action, which hung up in silence).
GOODBYE_FILLER = "Thanks for calling. Goodbye!"
MAX_EVENT_OUTPUT = 4096
LOOKUP_TYPES = frozenset({"http", "kb_search"})
EMPTY_OBJECT: dict[str, Any] = {"type": "object", "properties": {}, "required": []}


# Function shapes -------------------------------------------------------------------------------


def function_schema(spec: ToolSpecView) -> dict[str, Any]:
    """Raw function schema (name, description, parameters) the LLM sees for ``spec``."""
    config = spec.config
    description = spec.description
    parameters: dict[str, Any] = dict(EMPTY_OBJECT)
    if spec.type == "transfer_call" and config.get("routing_type") == "dynamic":
        instructions = str(config.get("routing_instructions") or "").strip()
        description = f"{description}\n\nHow to choose the number: {instructions}".strip()
        allowed = [str(n) for n in config.get("allowed_numbers") or []]
        destination: dict[str, Any] = {
            "type": "string",
            "description": "Phone number to transfer to, in +E.164 form",
            "pattern": r"^\+[1-9]\d{6,14}$",
        }
        if allowed:
            destination["enum"] = allowed
        parameters = {
            "type": "object",
            "properties": {"destination": destination},
            "required": ["destination"],
        }
    elif spec.type == "end_call":
        parameters = {
            "type": "object",
            "properties": {
                "goodbye": {
                    "type": "string",
                    "description": (
                        "Only if you have not said goodbye in this reply yet: the one short "
                        "sentence you say as you hang up, fitting the conversation, for example "
                        "confirming the callback or next step."
                    ),
                }
            },
        }
    elif spec.type == "press_digit":
        parameters = {
            "type": "object",
            "properties": {
                "digits": {
                    "type": "string",
                    "description": "Keypad digits to press: 0-9, * and #",
                    "pattern": r"^[0-9*#]{1,20}$",
                }
            },
            "required": ["digits"],
        }
    elif spec.type == "http":
        parameters = dict(config.get("parameters") or EMPTY_OBJECT)
    elif spec.type == "kb_search":
        parameters = {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "What to look up"}},
            "required": ["query"],
        }
    parameters.setdefault("properties", {})
    return {"name": spec.name, "description": description, "parameters": parameters}


_TYPES: Mapping[str, tuple[type, ...]] = {
    "string": (str,),
    "integer": (int,),
    "number": (int, float),
    "boolean": (bool,),
    "object": (dict,),
    "array": (list,),
    "null": (type(None),),
}


def _type_ok(value: Any, expected: Any) -> bool:
    names = expected if isinstance(expected, list) else [expected]
    for name in names:
        kinds = _TYPES.get(str(name))
        if kinds is None:
            return True
        if isinstance(value, bool) and name in ("integer", "number"):
            continue
        if isinstance(value, kinds):
            return True
    return False


def validate_arguments(schema: Mapping[str, Any], value: Any, path: str = "") -> str | None:
    """A small JSON Schema check (type, required, enum, pattern, lengths, ranges, nesting)."""
    where = path or "arguments"
    if "type" in schema and not _type_ok(value, schema["type"]):
        return f"{where} must be {schema['type']}"
    if "enum" in schema and value not in schema["enum"]:
        return f"{where} must be one of {schema['enum']}"
    if isinstance(value, str):
        if "pattern" in schema and not re.search(str(schema["pattern"]), value):
            return f"{where} has the wrong format"
        if len(value) < int(schema.get("minLength", 0)):
            return f"{where} is too short"
        if "maxLength" in schema and len(value) > int(schema["maxLength"]):
            return f"{where} is too long"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            return f"{where} is below {schema['minimum']}"
        if "maximum" in schema and value > schema["maximum"]:
            return f"{where} is above {schema['maximum']}"
    if isinstance(value, dict):
        for name in schema.get("required") or []:
            if name not in value or value[name] is None:
                return f"{name} is required"
        props = schema.get("properties") or {}
        for name, sub in props.items():
            if name in value and value[name] is not None and isinstance(sub, Mapping):
                problem = validate_arguments(sub, value[name], f"{path}.{name}" if path else name)
                if problem:
                    return problem
    if isinstance(value, list) and isinstance(schema.get("items"), Mapping):
        for i, item in enumerate(value):
            problem = validate_arguments(schema["items"], item, f"{where}[{i}]")
            if problem:
                return problem
    return None


# Fillers --------------------------------------------------------------------------------------


@dataclass
class FillerPolicy:
    """Lookup tools (and end_call) and what to say at once when the model calls one before
    speaking."""

    texts: dict[str, str] = field(default_factory=dict)
    # Set by the agent's llm_node: did the reply say anything before its tool calls?
    reply_spoke: bool = False
    # end_call tools: a goodbye the model wrote into the call replaces the canned filler.
    end_call_names: frozenset[str] = frozenset()

    def text_for(self, names: Sequence[str]) -> str | None:
        for name in names:
            if name in self.texts:
                return self.texts[name]
        return None


def filler_texts(specs: Sequence[ToolSpecView]) -> dict[str, str]:
    texts: dict[str, str] = {}
    for spec in specs:
        if spec.type == "kb_search":
            texts[spec.name] = FILLER_TEXT
        elif spec.type == "http" and spec.config.get("speak_during_execution", True):
            texts[spec.name] = str(spec.config.get("execution_message") or FILLER_TEXT)
        elif spec.type == "end_call":
            texts[spec.name] = str(spec.config.get("message") or "").strip() or GOODBYE_FILLER
    return texts


# Per-call tools -------------------------------------------------------------------------------


def specs_from(config: Mapping[str, Any]) -> list[ToolSpecView]:
    return [
        ToolSpecView.from_snapshot(t) for t in config.get("tools") or [] if isinstance(t, Mapping)
    ]


def kb_spec(config: Mapping[str, Any]) -> ToolSpecView | None:
    knowledge = [k for k in config.get("knowledge") or [] if isinstance(k, Mapping)]
    kb_ids = [str(k["kb_id"]) for k in knowledge if k.get("kb_id")] or [
        str(k) for k in config.get("kb_ids") or []
    ]
    if not kb_ids:
        return None
    return ToolSpecView(
        tool_id=None,
        type="kb_search",
        name=kb_search.TOOL_NAME,
        description=kb_search.description(knowledge),
        config={"kb_ids": kb_ids},
    )


SpeakFactory = Callable[[Any], Callable[[str], Any] | None]


@dataclass
class CallTools:
    """Tools of one call: specs, executors, shared context and the dispatch path."""

    control: CallControl
    specs: list[ToolSpecView]
    executors: dict[str, ToolExecutor]
    ctx: ToolContext
    fillers: FillerPolicy
    kb: ToolSpecView | None = None
    still_checking_after_s: float = STILL_CHECKING_AFTER_S
    clients: list[httpx.AsyncClient] = field(default_factory=list)

    @property
    def by_name(self) -> dict[str, ToolSpecView]:
        found = {s.name: s for s in self.specs}
        if self.kb is not None:
            found[self.kb.name] = self.kb
        return found

    def schemas(self, *, kb_search_enabled: bool = True) -> list[dict[str, Any]]:
        specs = list(self.specs)
        if self.kb is not None and kb_search_enabled:
            specs.append(self.kb)
        return [function_schema(s) for s in specs]

    def function_tools(self, *, kb_search_enabled: bool = True) -> list[Any]:
        return [
            _raw_tool(self, schema) for schema in self.schemas(kb_search_enabled=kb_search_enabled)
        ]

    def _context(self, run_ctx: Any) -> ToolContext:
        if run_ctx is None:
            return self.ctx
        session = getattr(run_ctx, "session", None)
        if session is None:
            return self.ctx

        async def say(text: str) -> None:
            handle = session.say(text, add_to_chat_ctx=False)
            with contextlib.suppress(Exception):
                await handle

        # A shallow copy: the variable stores and secrets stay shared with the call.
        return replace(
            self.ctx, say=say, wait_for_playout=getattr(run_ctx, "wait_for_playout", None)
        )

    async def _run(
        self, spec: ToolSpecView, args: Mapping[str, Any], ctx: ToolContext
    ) -> ToolResult:
        if ctx.simulation and spec.type == "http":
            if ctx.simulated_answer is not None:
                return await ctx.simulated_answer(spec, args, ctx)
            return simulated_http(spec, ctx)
        executor = self.executors.get(spec.type)
        if executor is None:
            return ToolResult.error("internal", f"No executor for {spec.type} tools.")
        return await executor.execute(spec, args, ctx)

    async def dispatch(
        self, name: str, raw_arguments: Mapping[str, Any] | None, run_ctx: Any = None
    ) -> str:
        started = time.perf_counter()
        spec = self.by_name.get(name)
        args = dict(raw_arguments or {})
        if spec is None:
            return ToolResult.error("invalid_arguments", f"Unknown tool {name}.").llm_payload
        ctx = self._context(run_ctx)
        problem = validate_arguments(function_schema(spec)["parameters"], args)
        exec_started = exec_ended = time.perf_counter()
        attrs = {"call_id": ctx.call_id, "tool.type": spec.type, "tool.name": spec.name}
        with telemetry.span("tool.execute", attrs) as span:
            if problem:
                result = ToolResult.error("invalid_arguments", problem)
            else:
                still = self._still_checking(spec, ctx)
                exec_started = time.perf_counter()
                try:
                    result = await self._run(spec, args, ctx)
                except Exception as exc:  # an executor bug must not end the call
                    log.exception("tool %s failed on %s", spec.name, ctx.call_id)
                    result = ToolResult.error(
                        "internal", f"The tool failed ({type(exc).__name__})."
                    )
                finally:
                    exec_ended = time.perf_counter()
                    if still is not None and not still.done():
                        still.cancel()
                        with contextlib.suppress(asyncio.CancelledError):
                            await still
            duration_ms = round((time.perf_counter() - started) * 1000)
            overhead_ms = max(0, duration_ms - round((exec_ended - exec_started) * 1000))
            span.set_attribute("tool.is_error", result.is_error)
            span.set_attribute("tool.duration_ms", duration_ms)
        self._report(spec, args, result, ctx, duration_ms, overhead_ms)
        return result.llm_payload

    def _still_checking(self, spec: ToolSpecView, ctx: ToolContext) -> asyncio.Task[None] | None:
        if spec.type not in ("http", "kb_search") or spec.name not in self.fillers.texts:
            return None

        async def later() -> None:
            await asyncio.sleep(self.still_checking_after_s)
            await ctx.speak(STILL_CHECKING)

        return asyncio.create_task(later())

    def _report(
        self,
        spec: ToolSpecView,
        args: Mapping[str, Any],
        result: ToolResult,
        ctx: ToolContext,
        duration_ms: int,
        overhead_ms: int,
    ) -> None:
        values = list(ctx.secrets.values())
        output = secrets.scrub(
            result.output if result.output is not None else result.llm_payload, values
        )
        clean_args = json.loads(secrets.scrub(json.dumps(args, default=str), values))
        extra: dict[str, Any] = {
            "tool_id": spec.tool_id,
            "tool_type": spec.type,
            "error_code": result.error_code,
            "dispatch_overhead_ms": overhead_ms,
            "mocked": result.mocked,
            **{k: v for k, v in result.extra.items() if k != "missing_paths"},
        }
        turn = ctx.turn_index()
        if turn is not None:
            extra["turn_index"] = turn
        try:
            ctx.control.report_tool(
                ToolActivity(
                    spec.name,
                    ref=spec.tool_id,
                    arguments=clean_args,
                    output=output[:MAX_EVENT_OUTPUT],
                    is_error=result.is_error,
                    duration_ms=duration_ms,
                    extra=extra,
                )
            )
        except Exception:  # reporting must never break the call
            log.exception("could not record tool call %s", spec.name)

    async def aclose(self) -> None:
        for client in self.clients:
            with contextlib.suppress(Exception):
                await client.aclose()


def simulated_http(spec: ToolSpecView, ctx: ToolContext) -> ToolResult:
    """Canned response instead of the network (R20, FR-044)."""
    mock = (spec.mock_response or "").strip()
    if not mock:
        result = ToolResult.error("no_mock_response", "This tool has no canned response.")
        result.mocked = True
        return result
    mapped, _ = http_core.apply_mappings(mock, list(spec.config.get("response_mappings") or []))
    ctx.mapped_variables.update(mapped)
    payload = http_core.success_payload(mock)
    return ToolResult(
        llm_payload=payload, output=payload, mocked=True, extra={"mapped_variables": mapped}
    )


def _raw_tool(tools: CallTools, schema: dict[str, Any]) -> Any:
    from livekit.agents import RunContext, function_tool

    name = str(schema["name"])

    ends_call = getattr(tools.by_name.get(name), "type", None) == "end_call"

    async def handler(raw_arguments: dict[str, object], context: RunContext) -> str:  # type: ignore[type-arg]
        payload = await tools.dispatch(name, raw_arguments, context)
        if ends_call:
            # The call is over: no follow-up reply from the model (it would talk over the hang-up).
            from livekit.agents.llm import StopResponse

            raise StopResponse()
        return payload

    handler.__annotations__ = {"raw_arguments": dict, "context": RunContext, "return": str}
    return function_tool(handler, raw_schema=schema)


def is_simulation(runtime: RuntimeConfig) -> bool:
    extra = runtime.model_extra or {}
    return bool(extra.get("simulation") or runtime.config.get("simulation"))


BUILTIN_END_CALL = ToolSpecView(
    tool_id=None,
    type="end_call",
    name="end_call",
    description=(
        "Hang up the call. Call it in the same reply as your goodbye, or right away when the "
        "caller says goodbye or thanks you after your goodbye. Never speak after calling it."
    ),
)


def build_call_tools(
    runtime: RuntimeConfig,
    control: CallControl,
    *,
    tool_secrets: Mapping[str, str] | None = None,
    http_client: httpx.AsyncClient | None = None,
    api_client: httpx.AsyncClient | None = None,
    api_base_url: str = "",
    service_token: str = "",
    transfer_backend: TransferBackend | None = None,
    allow_http: bool = False,
    resolver: Any = None,
    press_digit: PressDigitExecutor | None = None,
) -> CallTools:
    """Pure assembly (no I/O): the caller owns the clients unless they end up in ``clients``."""
    config = runtime.config
    specs = specs_from(config)
    # Every single-prompt agent can hang up, even when its tools do not list end_call.
    if not any(s.type == "end_call" or s.name == BUILTIN_END_CALL.name for s in specs):
        specs.append(BUILTIN_END_CALL)
    kb = kb_spec(config)
    clients: list[httpx.AsyncClient] = []
    simulation = is_simulation(runtime)
    if http_client is None and not simulation and any(s.type == "http" for s in specs):
        http_client = httpx.AsyncClient(follow_redirects=False)
        clients.append(http_client)
    executors: dict[str, ToolExecutor] = {
        "end_call": EndCallExecutor(),
        "transfer_call": TransferExecutor(transfer_backend),
        "press_digit": press_digit or PressDigitExecutor(),
    }
    if http_client is not None:
        executors["http"] = HttpExecutor(http_client, allow_http=allow_http, resolver=resolver)
    if kb is not None:
        if api_client is None:
            api_client = httpx.AsyncClient(timeout=kb_search.TIMEOUT_S)
            clients.append(api_client)
        executors["kb_search"] = kb_search.KbSearchExecutor(
            api_client, api_base_url, service_token, list(kb.config["kb_ids"])
        )
    fillers = FillerPolicy(
        filler_texts([*specs, *([kb] if kb else [])]),
        end_call_names=frozenset(s.name for s in specs if s.type == "end_call"),
    )
    ctx = ToolContext(
        control=control,
        channel=runtime.channel,
        simulation=simulation,
        dynamic_variables=dict(runtime.variables),
        secrets=dict(tool_secrets or {}),
        reply_spoke=lambda: fillers.reply_spoke,
    )
    return CallTools(control, specs, executors, ctx, fillers, kb, clients=clients)


# Provider -------------------------------------------------------------------------------------


class CallwrightToolProvider:
    """The registered :class:`~worker.tools.ToolProvider`. ``prepare`` runs at session start
    (secret fetch, keep-alive clients); ``tools_for`` then hands the LLM its function tools."""

    def __init__(self) -> None:
        self.calls: dict[str, CallTools] = {}
        self._adhoc: weakref.WeakKeyDictionary[Any, CallTools] = weakref.WeakKeyDictionary()

    async def prepare(
        self,
        runtime: RuntimeConfig,
        control: CallControl,
        settings: WorkerSettings,
        *,
        transfer_backend: TransferBackend | None = None,
    ) -> CallTools:
        base = settings.internal_api_url
        token = settings.service_token.get_secret_value()
        api_client = httpx.AsyncClient(timeout=settings.http_timeout_s)
        tool_secrets: dict[str, str] = {}
        if secrets.needs_secrets(runtime.config):
            tool_secrets = await secrets.fetch(api_client, base, token, control.call_id)
        tools = build_call_tools(
            runtime,
            control,
            tool_secrets=tool_secrets,
            api_client=api_client,
            api_base_url=base,
            service_token=token,
            transfer_backend=transfer_backend,
        )
        tools.clients.append(api_client)
        self.calls[control.call_id] = tools
        return tools

    def _for(self, runtime: RuntimeConfig, control: CallControl) -> CallTools:
        """The prepared tools of the call, else tools without secrets for this control (offline
        harness and tests), kept as long as the control lives."""
        call_id = getattr(control, "call_id", None)
        prepared = self.calls.get(call_id) if isinstance(call_id, str) else None
        if prepared is not None:
            return prepared
        try:
            found = self._adhoc.get(control)
        except TypeError:  # not weak-referenceable
            return build_call_tools(runtime, control)
        if found is None:
            found = build_call_tools(runtime, control)
            self._adhoc[control] = found
        return found

    def tools_for(self, runtime: RuntimeConfig, control: CallControl) -> Sequence[Any]:
        return self._for(runtime, control).function_tools()

    def call_tools(self, runtime: RuntimeConfig, control: CallControl) -> CallTools:
        """The call's tools, from which 004 builds each flow node's own tool set."""
        return self._for(runtime, control)

    def filler_policy(self, runtime: RuntimeConfig, control: CallControl) -> FillerPolicy:
        return self._for(runtime, control).fillers

    async def release(self, call_id: str) -> None:
        tools = self.calls.pop(call_id, None)
        if tools is not None:
            await tools.aclose()


PROVIDER = CallwrightToolProvider()
register_tool_provider(PROVIDER)
