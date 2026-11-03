"""Flow runtime on LiveKit Agents (T059, T066, T079, T080; research R10, R12, R13).

Each conversational node (agent, task) is its own agent built like 003's ``CallwrightAgent``
(voice style instruction, pronunciation and output gain in the TTS node, 005's spoken filler
before lookups) with its own instructions, tools and, when the node overrides them, its own
LLM, TTS and STT. Transitions are parameterless function tools; calling one hands the session
to the next node's agent (the framework's handoff). Non-conversational nodes run in the
executor between handoffs: a short-lived step agent runs them in ``on_enter`` and then hands
over to the conversational node the chain lands on.

The opening (who speaks first, greeting, leading Say nodes) is part of the session plan, so
003's pre-synthesised, uninterruptible greeting path plays it at once.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any

import httpx

from worker.adapters.registry import (
    AdapterRegistry,
    UnsupportedLanguage,
    UnsupportedVendor,
    VendorSpec,
)
from worker.flow import FLOW_NOT_COMPILED, FlowRuntimeUnavailable, llm_ops
from worker.flow import nodes as _handlers  # noqa: F401  (registers the node handlers)
from worker.flow.context import BackgroundSummarizer, Message, handoff, known_facts
from worker.flow.events import TOPIC, FlowEvents
from worker.flow.executor import FlowRun, WebhookResult
from worker.flow.nodes.start import Opening, opening
from worker.flow.registry import CONVERSATIONAL, Move
from worker.flow.templating import as_text
from worker.tools import CallControl, ToolActivity
from worker.tools.base import ToolSpecView
from worker.tools.http import HttpExecutor
from worker.tools.registry import CallTools, FillerPolicy, filler_texts, simulated_http

if TYPE_CHECKING:
    from worker.internal_api import RuntimeConfig
    from worker.pipeline import SessionPlan

log = logging.getLogger("callwright.flow")
GREETING_WAIT_S = 20.0
COMPLETE_TASK = "complete_task"
IGNORED = "Ignored: the call already moved to another step this turn."


@dataclass(frozen=True)
class FlowComponents:
    """How the runtime builds a node's own LLM, TTS or STT (from ``LiveCall``)."""

    registry: AdapterRegistry
    build: Callable[[VendorSpec], Any]
    on_timing: Callable[[str, int], None] | None = None


def flow_block(config: Mapping[str, Any]) -> Mapping[str, Any] | None:
    flow = config.get("flow")
    compiled = flow.get("compiled") if isinstance(flow, Mapping) else None
    return (
        compiled if isinstance(compiled, Mapping) and compiled.get("schema_version") == 1 else None
    )


def call_opening(config: Mapping[str, Any], variables: Mapping[str, Any]) -> Opening | None:
    compiled = flow_block(config)
    return opening(compiled, variables) if compiled is not None else None


def node_tools(base: CallTools, node: Mapping[str, Any]) -> CallTools:
    """The node's tool set: its compiled tools plus knowledge search when switched on, sharing
    the call's executors, secrets and variable stores."""
    specs = [
        ToolSpecView.from_snapshot(t) for t in node.get("tools") or [] if isinstance(t, Mapping)
    ]
    kb = base.kb if (node.get("kb_search") or {}).get("enabled") else None
    executors = dict(base.executors)
    if any(s.type == "http" for s in specs) and "http" not in executors and not base.ctx.simulation:
        client = httpx.AsyncClient(follow_redirects=False)
        base.clients.append(client)
        executors["http"] = HttpExecutor(client)
    fillers = FillerPolicy(
        filler_texts([*specs, *([kb] if kb else [])]),
        end_call_names=frozenset(s.name for s in specs if s.type == "end_call"),
    )
    ctx = replace(base.ctx, reply_spoke=lambda: fillers.reply_spoke)
    return CallTools(base.control, specs, executors, ctx, fillers, kb, clients=[])


class LiveFlowServices:
    """``FlowServices`` over the running ``AgentSession`` and 005's executors."""

    def __init__(self, call: FlowCall) -> None:
        self.call = call

    async def say(self, text: str, *, allow_interruptions: bool = True) -> None:
        session = self.call.session
        if session is None:
            await self.call.control.say(text, allow_interruptions=allow_interruptions)
            return
        handle = session.say(text, allow_interruptions=allow_interruptions)
        with contextlib.suppress(Exception):
            await handle

    def _llm(self) -> Any:
        session = self.call.session
        return getattr(session, "llm", None) if session is not None else None

    async def classify(self, instructions: str, categories: list[Mapping[str, Any]]) -> str | None:
        llm = self._llm()
        if llm is None:
            return None
        return await llm_ops.classify(llm, self.call.history(), instructions, categories)

    async def extract(self, instructions: str, schema: Mapping[str, Any]) -> dict[str, Any]:
        llm = self._llm()
        if llm is None:
            return {}
        return await llm_ops.extract(llm, self.call.history(), instructions, schema)

    async def webhook(
        self,
        node_id: str,
        request: Mapping[str, Any],
        mock_response: str | None,
        variables: Mapping[str, Any],
    ) -> WebhookResult:
        base = self.call.base_tools
        label = str(self.call.run.node(node_id).get("label") or node_id)
        spec = ToolSpecView(
            tool_id=None,
            type="http",
            name=f"webhook_{node_id}",
            description=label,
            config=dict(request),
            mock_response=mock_response,
        )
        self.call.sync_variables()
        ctx = replace(base.ctx, say=self._say_line)
        if ctx.simulation and ctx.simulated_answer is not None:
            result = await ctx.simulated_answer(spec, {}, ctx)
        elif ctx.simulation:
            result = simulated_http(spec, ctx)
        else:
            executor = base.executors.get("http")
            if executor is None:
                client = httpx.AsyncClient(follow_redirects=False)
                base.clients.append(client)
                executor = HttpExecutor(client)
                base.executors["http"] = executor
            result = await executor.execute(spec, {}, ctx)
        self.call.control.report_tool(
            ToolActivity(
                spec.name,
                arguments={},
                output=(result.output or result.llm_payload)[:2000],
                is_error=result.is_error,
                extra={
                    "tool_type": "http",
                    "flow_node_id": node_id,
                    "error_code": result.error_code,
                    **(
                        {"answer_source": result.extra["answer_source"]}
                        if "answer_source" in result.extra
                        else {}
                    ),
                },
            )
        )
        mapped = result.extra.get("mapped_variables") or {}
        return WebhookResult(ok=not result.is_error, mapped=dict(mapped), detail=result.error_code)

    async def transfer(self, node_id: str, spec: Mapping[str, Any]) -> bool:
        base = self.call.base_tools
        executor = base.executors.get("transfer_call")
        if executor is None:
            return False
        arguments: dict[str, Any] = {}
        if spec.get("routing_type") == "dynamic":
            allowed = [str(n) for n in spec.get("allowed_numbers") or []]
            arguments["destination"] = allowed[0] if allowed else ""
        view = ToolSpecView(None, "transfer_call", f"transfer_{node_id}", "Transfer", dict(spec))
        result = await executor.execute(view, arguments, replace(base.ctx, say=self._say_line))
        return not result.is_error

    async def end(self, message: str, reason: str) -> None:
        if message:
            await self.say(message, allow_interruptions=False)
        await self.call.control.hang_up("agent_hangup")

    async def hang_up(self, reason: str, diagnostic: str | None = None) -> None:
        await self.call.control.hang_up(reason, diagnostic=diagnostic)

    async def _say_line(self, text: str) -> None:
        await self.say(text)


class FlowCall:
    """Everything one flow call needs across its node agents."""

    def __init__(
        self,
        runtime: RuntimeConfig,
        control: CallControl,
        plan: SessionPlan,
        *,
        extra_tools: Sequence[Any] = (),
        extra_instructions: str = "",
        on_tts_text: Callable[[str], None] | None = None,
        components: FlowComponents | None = None,
        base_tools: CallTools | None = None,
    ) -> None:
        compiled = flow_block(runtime.config)
        if compiled is None:
            raise FlowRuntimeUnavailable("the flow did not compile", diagnostic=FLOW_NOT_COMPILED)
        self.runtime = runtime
        self.control = control
        self.plan = plan
        self.extra_tools = list(extra_tools)
        self.extra_instructions = extra_instructions
        self.on_tts_text = on_tts_text
        self.components = components
        self.compiled = compiled
        variables: dict[str, Any] = dict(runtime.variables)
        self.events = FlowEvents(
            control,
            offset_ms=_offset(control),
            publish=_publisher(control),
            turn_index=lambda: self.turns,
        )
        self.services = LiveFlowServices(self)
        self.run = FlowRun(
            compiled,
            self.services,
            self.events,
            variables,
            call_id=getattr(control, "call_id", None),
        )
        if base_tools is None:
            from worker.tools.registry import PROVIDER

            base_tools = PROVIDER.call_tools(runtime, control)
        self.base_tools = base_tools
        if components is not None and components.on_timing is not None:
            timing = components.on_timing
            self.run.on_engine = lambda ms: timing("engine_ms", ms)
        self.summarizer = BackgroundSummarizer(self._summarize)
        self.uses_summary = any(
            n.get("context_strategy") == "summarize" for n in compiled["nodes"].values()
        )
        self.session: Any = None
        self.current_agent: Any = None
        self.turns = 0
        self.greeting_done = asyncio.Event()
        self.opening = opening(compiled, variables)
        self._listening = False
        self._pending_llm_timing = False

    # session wiring ------------------------------------------------------------------------

    def attach(self, session: Any) -> None:
        if self.session is session:
            return
        self.session = session
        if self._listening or session is None:
            return
        self._listening = True
        with contextlib.suppress(Exception):
            session.on("conversation_item_added", self._on_item)
            session.on("metrics_collected", self._on_metrics)

    def _on_item(self, ev: Any) -> None:
        role = getattr(ev.item, "role", None)
        if role == "user":
            self.turns += 1
        elif role == "assistant":
            self.greeting_done.set()
            if self.uses_summary:
                self.summarizer.schedule(self.history())

    def _on_metrics(self, ev: Any) -> None:
        metrics = getattr(ev, "metrics", None)
        if not self._pending_llm_timing or getattr(metrics, "type", None) != "llm_metrics":
            return
        self._pending_llm_timing = False
        ttft = getattr(metrics, "ttft", None)
        if ttft is not None and self.components is not None and self.components.on_timing:
            self.components.on_timing("transition_llm_ms", round(float(ttft) * 1000))

    def history(self) -> list[Message]:
        session = self.session
        if session is None:
            return []
        out: list[Message] = []
        for item in getattr(session.history, "items", []):
            role = getattr(item, "role", None)
            text = getattr(item, "text_content", None)
            if role in ("user", "assistant") and text:
                out.append((role, str(text)))
        return out

    async def _summarize(self, history: Sequence[Message], previous: str | None) -> str:
        llm = getattr(self.session, "llm", None)
        if llm is None:
            return previous or ""
        return await llm_ops.summarize(llm, history, previous)

    def control_ended(self) -> bool:
        return bool(getattr(self.control, "ending", False))

    def sync_variables(self) -> None:
        """Flow variables for 005's request templating (flat names only)."""
        store = self.base_tools.ctx.dynamic_variables
        for key, value in self.run.state.variables.items():
            if "." not in key:
                store[key] = as_text(value)

    # agents --------------------------------------------------------------------------------

    def entry_agent(self) -> Any:
        started = self.run.clock()
        for source, move in self.opening.moves:
            self.run.state.transition_count += 1
            self.run.record(source, move, started)
        if self.opening.entry_node_id is not None:
            return self.agent_for(self.opening.entry_node_id, initial=True)
        if self.opening.next is not None:
            source, move = self.opening.next
            return self.step_agent(source, move, wait_for_greeting=bool(self.opening.greeting))
        return self.step_agent(None, None)

    def agent_for(self, node_id: str, *, initial: bool = False, chat_ctx: Any = None) -> Any:
        return flow_agent_classes()[0](self, node_id, initial=initial, chat_ctx=chat_ctx)

    def step_agent(
        self,
        source: str | None,
        move: Move | None,
        *,
        wait_for_greeting: bool = False,
        chat_ctx: Any = None,
    ) -> Any:
        return flow_agent_classes()[1](
            self, source, move, wait_for_greeting=wait_for_greeting, chat_ctx=chat_ctx
        )

    async def handoff_to(self, from_id: str, move: Move, chat_ctx: Any) -> Any:
        """The agent that continues the call after ``move`` (a node agent or a step agent)."""
        target = self.run.node(move.target)
        if target.get("type") in CONVERSATIONAL:
            landing = await self.run.advance(from_id, move)
            self.sync_variables()
            return self.agent_for(landing.node_id, chat_ctx=chat_ctx) if landing.node_id else None
        return self.step_agent(from_id, move, chat_ctx=chat_ctx)

    def node_chat_ctx(self, strategy: str, previous: Any) -> tuple[Any, str]:
        """Chat context and extra instructions for a node entered with ``strategy``."""
        from livekit.agents import llm as lk_llm

        if previous is None or strategy == "inherit":
            return (previous.copy() if previous is not None else None), ""
        result = handoff(
            strategy, self.history(), self.summarizer.summary, self.run.state.variables
        )
        ctx = lk_llm.ChatContext.empty()
        for role, text in result.messages:
            ctx.add_message(role="user" if role == "user" else "assistant", content=text)
        extra = known_facts(result.facts)
        if result.summary:
            extra = f"Summary of the call so far: {result.summary}"
        return ctx, extra

    def node_components(self, node: Mapping[str, Any]) -> dict[str, Any]:
        """The node's own LLM, TTS and STT when they differ from the call's (per-node overrides)."""
        if self.components is None:
            return {}
        from worker.pipeline import resolve_llm, resolve_stt, resolve_tts

        registry = self.components.registry
        language = str(node.get("language") or self.plan.language)
        out: dict[str, Any] = {}
        try:
            llm = resolve_llm({"llm": node.get("llm") or {}}, registry)
            if llm != self.plan.llm:
                out["llm"] = self.components.build(llm)
            tts = resolve_tts({"tts": node.get("tts") or {}}, registry, language=language)
            if tts != self.plan.tts:
                out["tts"] = self.components.build(tts)
                out["_tts_spec"] = tts
            stt, _ = resolve_stt({"stt": node.get("stt") or {}}, registry, language=language)
            if stt != self.plan.stt:
                out["stt"] = self.components.build(stt)
        except (UnsupportedVendor, UnsupportedLanguage) as exc:
            log.warning(
                "node override not applied on %s: %s", getattr(self.control, "call_id", "?"), exc
            )
        return out


def _offset(control: Any) -> Callable[[], int | None]:
    recorder = getattr(control, "_recorder", None)
    fn = getattr(recorder, "offset_ms", None)
    return fn if callable(fn) else (lambda: None)


def _publisher(control: Any) -> Any:
    room = getattr(control, "room", None)
    participant = getattr(room, "local_participant", None)
    if participant is None:
        return None

    async def publish(data: bytes) -> None:
        await participant.publish_data(data, reliable=True, topic=TOPIC)

    return publish


_classes: tuple[type[Any], type[Any]] | None = None


def flow_agent_classes() -> tuple[type[Any], type[Any]]:
    """``(FlowNodeAgent, FlowStepAgent)``, built lazily so pure tests never import LiveKit."""
    global _classes
    if _classes is not None:
        return _classes
    from worker.pipeline import make_agent_class, tts_gain_for

    base: type[Any] = make_agent_class()

    class FlowNodeAgent(base):  # type: ignore[misc]
        """One conversational node: its instructions, tools, transitions and components."""

        def __init__(
            self, call: FlowCall, node_id: str, *, initial: bool, chat_ctx: Any = None
        ) -> None:
            self.call = call
            self.node_id = node_id
            self.node = call.run.node(node_id)
            self.initial = initial
            self.rounds = 0
            self.completed = False
            node = self.node
            ctx, extra = call.node_chat_ctx(
                str(node.get("context_strategy") or "inherit"), chat_ctx
            )
            instructions = call.run.render(node.get("instructions"))
            task = node.get("task")
            if task:
                fields = ", ".join((task.get("json_schema") or {}).get("properties", {}).keys())
                extra = "\n\n".join(
                    p
                    for p in (
                        extra,
                        f"Collect these details from the caller: {fields}. Once you have them, "
                        f"call {COMPLETE_TASK} with the values.",
                    )
                    if p
                )
            components = call.node_components(node)
            plan = replace(call.plan, instructions=instructions)
            tts_spec = components.pop("_tts_spec", None)
            if tts_spec is not None:
                plan = replace(plan, tts=tts_spec, tts_gain=tts_gain_for(tts_spec))
            tools_set = node_tools(call.base_tools, node)
            tools = [*tools_set.function_tools(), *self._transition_tools(), *call.extra_tools]
            if task:
                tools.append(self._task_tool(task))
            kwargs: dict[str, Any] = dict(components)
            if ctx is not None:
                kwargs["chat_ctx"] = ctx
            super().__init__(
                plan,
                tools=tools,
                on_tts_text=call.on_tts_text,
                extra_instructions="\n\n".join(p for p in (extra, call.extra_instructions) if p),
                filler_policy=tools_set.fillers,
                **kwargs,
            )

        def _transition_tools(self) -> list[Any]:
            out = []
            for t in self.node.get("transitions") or []:
                name = str(t["function_name"])

                async def run(_args: dict[str, Any], _ctx: Any, name: str = name) -> Any:
                    return await self._take(name)

                out.append(
                    llm_ops.raw_tool(
                        name,
                        str(t.get("description") or ""),
                        {"type": "object", "properties": {}},
                        run,
                    )
                )
            return out

        def _task_tool(self, task: Mapping[str, Any]) -> Any:
            schema = dict(task.get("json_schema") or {"type": "object", "properties": {}})

            async def run(args: dict[str, Any], _ctx: Any) -> Any:
                required = [str(r) for r in schema.get("required") or []]
                missing = [r for r in required if args.get(r) in (None, "")]
                if missing:
                    return f"Still missing: {', '.join(missing)}. Ask the caller for them."
                return await self._complete(args, complete=True)

            return llm_ops.raw_tool(
                COMPLETE_TASK, "Save the collected details and continue.", schema, run
            )

        async def _take(self, function_name: str) -> Any:
            call = self.call
            if not call.run.claim_turn(call.turns):
                return IGNORED
            move = call.run.transition_move(self.node_id, function_name)
            if move is None:
                return "Unknown transition."
            agent = await call.handoff_to(self.node_id, move, self.chat_ctx)
            return agent if agent is not None else "The call has ended."

        async def _complete(self, values: Mapping[str, Any], *, complete: bool) -> Any:
            call = self.call
            self.completed = True
            task = self.node.get("task") or {}
            found = {k: v for k, v in values.items() if v not in (None, "")}
            variables: dict[str, Any] = {f"task_result.{k}": v for k, v in found.items()}
            variables["task_result"] = dict(found)
            if not task.get("success_target"):
                return "There is no next step."
            if not call.run.claim_turn(call.turns) and complete:
                return IGNORED
            move = Move(
                target=str(task["success_target"]),
                trigger="success",
                edge_id=task.get("success_edge_id"),
                variables=variables,
                note=None if complete else f"max rounds reached after {self.rounds}",
            )
            agent = await call.handoff_to(self.node_id, move, self.chat_ctx)
            return agent if agent is not None else "The call has ended."

        async def on_enter(self) -> None:
            call = self.call
            call.attach(self.session)
            call.current_agent = self
            if self.initial:
                return
            begin = call.run.render(self.node.get("begin_message")).strip()
            if begin:
                self.session.say(begin)
            else:
                call._pending_llm_timing = True
                self.session.generate_reply()

        async def llm_node(self, chat_ctx: Any, tools: list[Any], model_settings: Any) -> Any:
            """A task node that reached its maximum caller rounds completes with what it has
            instead of replying (FR-012)."""
            task = self.node.get("task")
            items = getattr(chat_ctx, "items", [])
            if task and items and getattr(items[-1], "role", None) == "user":
                self.rounds += 1
            if task and not self.completed and self.rounds >= int(task.get("max_rounds") or 5):
                self.completed = True
                call = self.call
                schema = dict(task.get("json_schema") or {})
                values = await call.services.extract(
                    call.run.render(self.node.get("instructions")), schema
                )
                agent = await self._complete(values, complete=False)
                if agent is not None and not isinstance(agent, str):
                    self.session.update_agent(agent)
                return
            async for chunk in super().llm_node(chat_ctx, tools, model_settings):
                yield chunk

    class FlowStepAgent(base):  # type: ignore[misc]
        """Runs non-conversational nodes, then hands over to the node the chain lands on."""

        def __init__(
            self,
            call: FlowCall,
            source: str | None,
            move: Move | None,
            *,
            wait_for_greeting: bool,
            chat_ctx: Any = None,
        ) -> None:
            self.call = call
            self.source = source
            self.move = move
            self.wait_for_greeting = wait_for_greeting
            self.carried_ctx = chat_ctx
            kwargs: dict[str, Any] = {"chat_ctx": chat_ctx} if chat_ctx is not None else {}
            super().__init__(
                replace(call.plan, instructions=""),
                tools=[],
                on_tts_text=call.on_tts_text,
                **kwargs,
            )

        async def on_enter(self) -> None:
            call = self.call
            call.attach(self.session)
            if self.move is None:
                await call.services.hang_up("error", diagnostic="flow_dead_end")
                return
            if self.wait_for_greeting:
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(call.greeting_done.wait(), timeout=GREETING_WAIT_S)
            landing = await call.run.advance(self.source, self.move)
            call.sync_variables()
            if landing.node_id is not None:
                self.session.update_agent(
                    call.agent_for(landing.node_id, chat_ctx=self.carried_ctx or self.chat_ctx)
                )
            elif not call.control_ended():
                await call.services.hang_up("error", diagnostic="flow_dead_end")

    _classes = (FlowNodeAgent, FlowStepAgent)
    return _classes


class CallwrightFlowRunner:
    """The registered ``FlowRunner`` (004)."""

    available = True

    def __init__(self) -> None:
        self.calls: dict[str, FlowCall] = {}

    def build_agent(
        self, runtime: RuntimeConfig, control: CallControl, tools: Sequence[Any], **options: Any
    ) -> Any:
        plan = options.get("plan")
        if plan is None:
            raise FlowRuntimeUnavailable("the flow runtime needs the session plan")
        call = FlowCall(
            runtime,
            control,
            plan,
            extra_tools=tools,
            extra_instructions=str(options.get("extra_instructions") or ""),
            on_tts_text=options.get("on_tts_text"),
            components=options.get("components"),
            base_tools=options.get("base_tools"),
        )
        call_id = getattr(control, "call_id", None)
        if isinstance(call_id, str):
            self.calls[call_id] = call
        return call.entry_agent()


RUNNER = CallwrightFlowRunner()
