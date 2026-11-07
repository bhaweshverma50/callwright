"""Text-mode session runner (008 T018, T037, T088; research R1, R4 to R6).

:class:`TextSession` builds a conversation from the same code as a live call:
:func:`~worker.pipeline.plan_session` and :func:`~worker.pipeline.build_agent` (004's flow
runner for flow agents), 005's call tools and :class:`~worker.control.RuntimeCallControl`,
on a LiveKit ``AgentSession`` with no STT, TTS or VAD: caller turns go in as text and the
agent's replies come back as text. ``RuntimeConfig.simulation`` is set, so no HTTP executor is
built and :mod:`worker.textsim.mock_tools` answers HTTP tools and webhook nodes.

Two job flows use it:

- :func:`run_single_turn` (test cases): the agent's opening when it speaks first, one caller
  turn, then the reply, tool calls and (flow agents) visited nodes are posted to
  ``/test-runs/{trn}/cases/{tc}/result``. No call exists; ``kb_search`` uses the test run id as
  its call id.
- :func:`run_simulation` (replay and persona): events go to the pre-created simulated call
  (``status in_progress``, ``transcript_item`` messages and tool items, ``tool_call`` and
  ``flow_transition`` events, a final ``usage`` and ``status ended``), then the run result to
  ``/simulation-runs/{srun}/result``. Simulated calls carry no latency: no ``turn`` events and
  no message timings are sent.

A spec answered with 404 or 409 means the run was cancelled or is gone: the job stops without
posting a result. Simulation events are posted after every agent turn and as a heartbeat at
least every ``heartbeat_interval_s`` while a turn runs; an events post answered with 409 (the API
closed the call) stops the run, and its result is ``failed`` with that reason.

Spans: ``textsim.test_case`` (``test_run_id``, ``test_case_id``, ``call_id``) and
``textsim.simulation`` (``simulation_run_id``, ``call_id``, mode), with a ``textsim.turn`` child
per caller turn; tool and flow spans of the shared code join them.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import httpx
from callwright_contract.calls import AgentType, Channel, Direction
from callwright_contract.protocol import RuntimeConfig, RuntimeValues
from callwright_contract.variables import BUILTIN_VARIABLES

from worker import telemetry
from worker.adapters.llm import supports_temperature
from worker.adapters.registry import AdapterRegistry, VendorSpec
from worker.call_behavior import ends_with_goodbye
from worker.control import RuntimeCallControl
from worker.flow.runtime import CallwrightFlowRunner, FlowComponents
from worker.metrics import EventPoster, EventRecorder
from worker.pipeline import (
    GENERATED_GREETING_INSTRUCTION,
    SessionPlan,
    build_agent,
    plan_session,
    resolve_llm,
)
from worker.textsim.api_client import SimulationSpec, TextsimApiClient
from worker.textsim.conversation import DISCONNECT_REASON, AgentTurn, Outcome
from worker.textsim.llm import ModelFactory, Role, TokenMeter, parse_model
from worker.textsim.mock_tools import SimulatedToolAnswers, install, tool_synthesizer
from worker.textsim.persona_caller import PERSONA_TEMPERATURE, PersonaCaller
from worker.textsim.replay_caller import ReplayCaller
from worker.tools.registry import CallTools, build_call_tools

log = logging.getLogger("callwright.textsim")

SETTLE_TICK_S = 0.01
QUIET_TICKS = 3
MAX_ERROR_CHARS = 2000


@dataclass
class RunnerDeps:
    """What a run needs besides the API client: models (adapters or the offline fallback), the
    vendor catalog, and the internal API location and client used by ``kb_search``."""

    models: ModelFactory
    registry: AdapterRegistry = field(default_factory=AdapterRegistry)
    internal_api_url: str = ""
    service_token: str = ""
    kb_http: httpx.AsyncClient | None = None
    settle_timeout_s: float = 60.0
    turn_timeout_s: float = 180.0
    # Events are posted after every agent turn and at least this often while a turn runs (an
    # empty batch is the heartbeat the API's stuck-call reaper looks for).
    heartbeat_interval_s: float = 10.0


CALL_CLOSED = "the API closed the simulated call (409 on events)"


class CallClosedByApi(Exception):
    """An events post was answered with 409: the run stops and its result is ``failed``."""


# --------------------------------------------------------------------------------------------
# Runtime from a snapshot


def build_runtime(
    values: RuntimeValues,
    *,
    agent_id: str,
    agent_type: AgentType,
    channel: Channel,
    variables: Mapping[str, str],
    call_id: str,
) -> RuntimeConfig:
    """The claim's runtime for a text run: the API's resolved values, the version's variable
    defaults and the built-ins (a text run has no phone numbers), then the run's own values."""
    config = values.config
    resolved: dict[str, str] = {
        str(v["name"]): str(v.get("default") or "")
        for v in config.get("dynamic_variables") or []
        if isinstance(v, Mapping) and v.get("name")
    }
    now = datetime.now(UTC)
    direction: Direction = "outbound" if channel == "sip_outbound" else "inbound"
    known = {
        "call_id": call_id,
        "channel": channel,
        "direction": direction,
        "timezone": "UTC",
        "current_time": now.strftime("%H:%M"),
        "current_date": now.strftime("%Y-%m-%d"),
        "current_datetime": now.isoformat(timespec="minutes"),
    }
    for name in BUILTIN_VARIABLES:
        resolved.setdefault(name, known.get(name, ""))
    resolved.update(variables)
    return RuntimeConfig(
        **dict(values),
        channel=channel,
        direction=direction,
        agent_id=agent_id,
        agent_version_id=str(config.get("agent_version_id") or "agv_snapshot"),
        agent_type=agent_type,
        variables=resolved,
        simulation=True,
    )


# --------------------------------------------------------------------------------------------
# Session


class _SimBackend:
    """``CallBackend`` of a text session: speech goes to the session as text; ending records
    the reason and stops the current reply (the runner closes the session afterwards)."""

    def __init__(self) -> None:
        self.session: Any = None

    async def speak(self, text: str, allow_interruptions: bool) -> None:
        if self.session is not None:
            self.session.say(text, allow_interruptions=allow_interruptions)

    async def end(self, reason: str, diagnostic: str | None) -> None:
        if self.session is not None:
            with contextlib.suppress(Exception):
                self.session.interrupt()

    async def send_dtmf(self, digits: str) -> None:
        return None  # keypad presses are only logged in simulations (the tool_call event)


class _Tools:
    """``ToolProvider`` over the session's own call tools (no shared registry state, so
    concurrent runs of one test run never collide)."""

    def __init__(self, tools: CallTools) -> None:
        self.tools = tools

    def tools_for(self, runtime: RuntimeConfig, control: Any) -> Sequence[Any]:
        return self.tools.function_tools()

    def call_tools(self, runtime: RuntimeConfig, control: Any) -> CallTools:
        return self.tools

    def filler_policy(self, runtime: RuntimeConfig, control: Any) -> Any:
        return self.tools.fillers


async def _wait(awaitable: Any) -> None:
    await awaitable


class TextSession:
    """One text conversation on the live session code (implements ``Conversation``)."""

    def __init__(
        self,
        call_id: str,
        runtime: RuntimeConfig,
        deps: RunnerDeps,
        *,
        answers: SimulatedToolAnswers,
        recorder: EventRecorder,
        meter: TokenMeter,
        on_turn: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        self.call_id = call_id
        self.runtime = runtime
        self.deps = deps
        self.answers = answers
        self.recorder = recorder
        self.meter = meter
        self.on_turn = on_turn
        self.backend = _SimBackend()
        self.control = RuntimeCallControl(call_id, recorder, self.backend)
        self.plan: SessionPlan | None = None
        self.session: Any = None
        self.tools: CallTools | None = None
        self.flow_runner = CallwrightFlowRunner()
        self._turn = 0
        self._texts: list[str] = []
        self._synth: Any = None
        self._error: str | None = None
        self._tasks: set[asyncio.Future[Any]] = set()

    # Conversation --------------------------------------------------------------------------

    @property
    def disconnect_reason(self) -> str | None:
        return self.control.disconnect_reason

    @property
    def diagnostic(self) -> str | None:
        return self.control.diagnostic

    @property
    def turn_index(self) -> int:
        return self._turn

    @property
    def is_flow(self) -> bool:
        return self.plan is not None and self.plan.agent_type == "flow"

    @property
    def visited_nodes(self) -> list[str]:
        call = self.flow_runner.calls.get(self.call_id)
        return list(call.run.state.visited) if call is not None else []

    # models --------------------------------------------------------------------------------

    def model(self, spec: VendorSpec, role: Role, context: Mapping[str, Any] | None = None) -> Any:
        """A model for ``role`` from the factory, metered under that role."""
        return self.meter.attach(self.deps.models(spec, role, context), role, spec)

    def synth_model(self) -> Any:
        """Tool stand-ins use the agent's model (built on first use)."""
        if self._synth is None:
            spec = self.plan.llm if self.plan is not None else resolve_llm({}, self.deps.registry)
            self._synth = self.model(VendorSpec("llm", spec.provider, spec.model), "synth")
        return self._synth

    def _component(self, spec: VendorSpec) -> Any:
        """A flow node's own components: its LLM; no speech components in text mode."""
        return self.model(spec, "agent") if spec.kind == "llm" else None

    # lifecycle -----------------------------------------------------------------------------

    async def start(self) -> AgentTurn:
        from livekit.agents import AgentSession

        runtime = self.runtime
        plan = plan_session(runtime, self.deps.registry)
        self.plan = plan
        tools = build_call_tools(
            runtime,
            self.control,
            api_client=self.deps.kb_http,
            api_base_url=self.deps.internal_api_url,
            service_token=self.deps.service_token,
        )
        self.tools = install(tools, self.answers)
        tools.ctx.turn_index = lambda: self._turn
        llm = self.model(plan.llm, "agent")
        agent = build_agent(
            plan,
            runtime,
            self.control,
            tool_provider=_Tools(tools),
            flow_runner=self.flow_runner,
            flow_components=FlowComponents(self.deps.registry, self._component),
        )
        session: Any = AgentSession(llm=llm, vad=None, user_away_timeout=None)
        self.session = session
        self.backend.session = session
        session.on("conversation_item_added", self._on_item)
        session.on("error", self._on_error)
        await session.start(agent)
        if plan.start_speaker == "agent":
            if plan.greeting:
                handle = session.say(plan.greeting, allow_interruptions=False)
            else:
                handle = session.generate_reply(instructions=GENERATED_GREETING_INSTRUCTION)
            await asyncio.wait_for(_wait(handle), self.deps.turn_timeout_s)
        await self._settle()
        return await self._finish_turn()

    async def send(self, text: str) -> AgentTurn:
        if self.session is None:
            raise RuntimeError("the session has not started")
        self._turn += 1
        self._texts = []
        self.recorder.message("user", text, started_ms=None, ended_ms=None, turn_index=self._turn)
        with telemetry.span("textsim.turn", {"turn_index": self._turn}):
            result = self.session.run(user_input=text)
            await asyncio.wait_for(_wait(result), self.deps.turn_timeout_s)
            await self._settle()
        return await self._finish_turn()

    async def aclose(self) -> None:
        if self.session is not None:
            with contextlib.suppress(Exception):
                await asyncio.wait_for(self.session.aclose(), self.deps.settle_timeout_s)
        if self.tools is not None:
            await self.tools.aclose()

    # internals -----------------------------------------------------------------------------

    def _busy(self) -> bool:
        session = self.session
        task = getattr(session, "_update_activity_atask", None)
        return (
            (task is not None and not task.done())
            or session.current_speech is not None
            or session.agent_state in ("thinking", "speaking")
            or self.answers.in_flight > 0
        )

    async def _settle(self) -> None:
        """Wait until the reply, its tool calls and any flow handoff have finished."""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.deps.settle_timeout_s
        quiet = 0
        while quiet < QUIET_TICKS and loop.time() < deadline:
            if self._busy():
                quiet = 0
                with contextlib.suppress(Exception):
                    await asyncio.wait_for(
                        self.session.wait_for_idle(), max(0.01, deadline - loop.time())
                    )
            else:
                quiet += 1
            await asyncio.sleep(SETTLE_TICK_S)

    async def _finish_turn(self) -> AgentTurn:
        if self._error is not None:
            raise RuntimeError(self._error)
        texts = list(self._texts)
        if texts and self.control.disconnect_reason is None and ends_with_goodbye(texts[-1]):
            # As on a live call: a goodbye with no reply from the caller ends the call.
            await self.control.hang_up("agent_hangup")
        if self.on_turn is not None:
            await self.on_turn()
        return AgentTurn(self._turn, texts, self.control.disconnect_reason)

    def _on_item(self, ev: Any) -> None:
        item = ev.item
        if (
            getattr(item, "type", "message") != "message"
            or getattr(item, "role", "") != "assistant"
        ):
            return
        text = str(getattr(item, "text_content", None) or "").strip()
        if not text:
            return
        self._texts.append(text)
        entry: dict[str, Any] = {
            "type": "message",
            "role": "agent",
            "text": text,
            "turn_index": self._turn,
        }
        node_id = None
        if self.is_flow:
            with contextlib.suppress(RuntimeError):
                node_id = getattr(self.session.current_agent, "node_id", None)
        if node_id:
            entry["node_id"] = node_id
        self.recorder.transcript_item(entry)

    def _on_error(self, ev: Any) -> None:
        error = getattr(ev, "error", ev)
        if getattr(error, "recoverable", False):
            return
        self._error = f"model error: {getattr(error, 'error', error)}"[:MAX_ERROR_CHARS]
        if self.control.disconnect_reason is None:
            task = asyncio.ensure_future(
                self.control.hang_up("error", diagnostic="vendor_error:llm")
            )
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)


# --------------------------------------------------------------------------------------------
# Results


def tool_records(recorder: EventRecorder) -> list[dict[str, Any]]:
    """``ToolCallRecord`` rows from the recorded ``tool_call`` events. ``answer_source`` is null
    for tools that are not answered by the simulation (end_call, transfer, kb_search, ...)."""
    rows = []
    for event in recorder.history:
        if event.get("type") != "tool_call":
            continue
        rows.append(
            {
                "name": event["name"],
                "arguments": dict(event.get("arguments") or {}),
                "output": event.get("output"),
                "answer_source": event.get("answer_source"),
            }
        )
    return rows


def _error_text(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {exc}"[:MAX_ERROR_CHARS]


# --------------------------------------------------------------------------------------------
# Single-turn test case (T037)


async def run_single_turn(
    api: TextsimApiClient, test_run_id: str, test_case_id: str, deps: RunnerDeps
) -> str:
    """Run one test case. Returns ``completed``, ``error`` or ``gone`` (cancelled run)."""
    attrs = {"test_run_id": test_run_id, "test_case_id": test_case_id, "call_id": test_run_id}
    with telemetry.call_scope(test_run_id), telemetry.span("textsim.test_case", attrs) as span:
        spec = await api.case_spec(test_run_id, test_case_id)
        if spec is None:
            span.set_attribute("textsim.outcome", "gone")
            return "gone"
        span.set_attribute("agent_type", spec.agent_type)
        started = time.perf_counter()
        recorder = EventRecorder()
        meter = TokenMeter()
        answers = SimulatedToolAnswers(policy="synthesize")
        session: TextSession | None = None
        body: dict[str, Any] = {
            "status": "completed",
            "agent_response": None,
            "error_message": None,
        }
        try:
            runtime = build_runtime(
                spec.runtime,
                agent_id=spec.agent_id,
                agent_type=spec.agent_type,
                channel="web",
                variables=spec.dynamic_variables,
                call_id=test_run_id,
            )
            session = TextSession(
                test_run_id, runtime, deps, answers=answers, recorder=recorder, meter=meter
            )
            answers.synthesize = tool_synthesizer(session.synth_model)
            await session.start()
            if session.disconnect_reason is None:
                reply = await session.send(spec.user_prompt)
                body["agent_response"] = " ".join(reply.texts) or None
        except Exception as exc:
            log.exception("test case %s/%s failed", test_run_id, test_case_id)
            body.update(status="error", error_message=_error_text(exc))
        finally:
            if session is not None:
                await session.aclose()
        body["tool_calls"] = tool_records(recorder)
        body["nodes_visited"] = session.visited_nodes if session is not None else []
        body["usage"] = meter.usage()
        body["duration_ms"] = round((time.perf_counter() - started) * 1000)
        span.set_attribute("textsim.outcome", body["status"])
        posted = await api.post_case_result(test_run_id, test_case_id, body)
        return str(body["status"]) if posted else "gone"


# --------------------------------------------------------------------------------------------
# Simulation (replay and persona)


def persona_spec(spec: SimulationSpec, runtime: RuntimeConfig, registry: AdapterRegistry) -> Any:
    default = resolve_llm(runtime.config, registry)
    chosen = parse_model(spec.settings.persona_model, VendorSpec("llm", default.provider, None))
    if chosen.model is None:
        chosen = VendorSpec("llm", default.provider, default.model)
    options = {"temperature": PERSONA_TEMPERATURE} if supports_temperature(chosen.model) else {}
    return VendorSpec("llm", chosen.provider, chosen.model, options)


async def run_simulation(api: TextsimApiClient, simulation_run_id: str, deps: RunnerDeps) -> str:
    """Run one simulation. Returns ``completed``, ``failed`` or ``gone`` (cancelled run)."""
    attrs = {"simulation_run_id": simulation_run_id}
    with telemetry.span("textsim.simulation", attrs) as span:
        spec = await api.simulation_spec(simulation_run_id)
        if spec is None:
            span.set_attribute("textsim.outcome", "gone")
            return "gone"
        call_id = spec.output_call_id
        telemetry.set_call_id(call_id, span)
        span.set_attribute("simulation.mode", spec.mode)
        span.set_attribute("agent_type", spec.agent_type)
        with telemetry.call_scope(call_id):
            status = await _simulate(api, spec, deps, span)
        span.set_attribute("textsim.outcome", status)
        return status


async def _simulate(
    api: TextsimApiClient, spec: SimulationSpec, deps: RunnerDeps, span: Any
) -> str:
    call_id = spec.output_call_id
    recorder = EventRecorder()
    meter = TokenMeter()
    session: TextSession | None = None

    async def on_control_end(reason: str) -> None:
        if session is not None:
            await session.control.hang_up(reason)

    poster = EventPoster(
        call_id,
        recorder,
        api,
        on_end_call=on_control_end,
        interval_s=deps.heartbeat_interval_s,
    )
    recorder.status("in_progress")
    await poster.flush(with_usage=False)

    async def on_turn() -> None:
        await poster.flush(with_usage=False)
        if poster.closed:
            raise CallClosedByApi(CALL_CLOSED)

    answers = SimulatedToolAnswers(
        policy=spec.settings.missing_mock_policy,
        recorded=spec.recorded_tool_outputs,
        replay=spec.mode == "replay",
    )
    status = "completed"
    error_message: str | None = None
    outcome = Outcome(end_reason="error")
    brief = spec.persona_brief.model_dump(exclude_none=True) if spec.persona_brief else None
    poster.start()  # heartbeat while a turn runs
    try:
        if poster.closed:
            raise CallClosedByApi(CALL_CLOSED)
        runtime = build_runtime(
            spec.runtime,
            agent_id=spec.agent_id,
            agent_type=spec.agent_type,
            channel=spec.channel,
            variables=spec.dynamic_variables,
            call_id=call_id,
        )
        session = TextSession(
            call_id,
            runtime,
            deps,
            answers=answers,
            recorder=recorder,
            meter=meter,
            on_turn=on_turn,
        )
        answers.synthesize = tool_synthesizer(session.synth_model)
        if spec.mode == "replay":
            caller = ReplayCaller(spec.caller_turns, spec.original_node_path)
            outcome = await caller.drive(session)
        else:
            if brief is None or not str(brief.get("goal") or "").strip():
                raise ValueError("persona runs need a persona brief with a goal")
            model = session.model(persona_spec(spec, runtime, deps.registry), "caller", brief)
            persona = PersonaCaller(model, brief, max_turns=spec.settings.max_caller_turns)
            outcome = await persona.drive(session)
        if outcome.end_reason == "error":
            status = "failed"
            reason = session.disconnect_reason or "error"
            error_message = f"the call ended with {reason}" + (
                f" ({session.diagnostic})" if session.diagnostic else ""
            )
    except CallClosedByApi as exc:
        status, error_message = "failed", str(exc)
        outcome = Outcome(end_reason="error")
    except Exception as exc:
        log.exception("simulation %s failed", spec.simulation_run_id)
        status, error_message = "failed", _error_text(exc)
        outcome = Outcome(end_reason="error")
    finally:
        await poster.stop()
        if session is not None:
            await session.aclose()

    agent = meter.rows.get("agent")
    if agent is not None:
        provider, _, model_id = str(agent["model"]).partition("/")
        recorder.meters.add_llm(
            provider,
            model_id,
            input_tokens=int(agent["input_tokens"]),
            cached_input_tokens=meter.cached.get("agent", 0),
            output_tokens=int(agent["output_tokens"]),
        )
    recorder.usage()
    recorder.status(
        "ended",
        disconnect_reason=DISCONNECT_REASON[outcome.end_reason],
        diagnostic=session.diagnostic if session is not None else None,
    )
    await poster.flush(with_usage=False)  # skipped when the API already closed the call
    if poster.closed and error_message is None:
        status, error_message = "failed", CALL_CLOSED

    span.set_attribute("simulation.end_reason", outcome.end_reason)
    result: dict[str, Any] = {
        "status": status,
        "end_reason": outcome.end_reason,
        "diverged_at_turn": outcome.diverged_at_turn,
        "answer_source_counts": dict(answers.counts),
        "usage": meter.usage(),
        "error_message": error_message,
    }
    if spec.mode == "persona" and brief is not None:
        result["persona_brief"] = brief
    posted = await api.post_simulation_result(spec.simulation_run_id, result)
    return status if posted else "gone"
