"""Worker entry point. ``WORKER_ROLE=live`` joins LiveKit rooms; ``textsim`` is owned by 008.

Live job sequence (003 plan, research R1, R2):

1. The dispatch carries ``{"call_id": ...}`` (web, outbound) or ``{"channel", "route_ref"}``
   (SIP inbound, WhatsApp; 010). The worker claims the job at ``POST /v1/internal/calls/claim``
   and receives the frozen :class:`RuntimeConfig`, or a refusal (hang up without speaking).
2. :func:`worker.pipeline.plan_session` resolves vendors; unsupported vendors or a flow agent
   without the 004 runtime fail the call with a diagnostic.
3. Web calls wait up to ``caller_join_timeout_s`` for the browser, then post ``in_progress``,
   start the session, the timers, background audio and the greeting.
4. Every events post is the heartbeat; ``control.end_call`` in a response ends the call.
5. Hang-up (any reason, first writer wins) posts the final ``ended`` status with usage, closes
   the session and deletes the room.

Run with ``python -m worker.entry start`` (LiveKit CLI) or ``dev`` locally.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import sys
import time
from collections.abc import Awaitable, Callable
from typing import Any

from worker import telemetry
from worker.adapters.registry import AdapterRegistry, Kind, UnsupportedLanguage, UnsupportedVendor
from worker.call_behavior import (
    VAD_MIN_SILENCE_S,
    VOICEMAIL_INSTRUCTION,
    VOICEMAIL_TOOL_NAME,
    AsyncioClock,
    DtmfCollector,
    DurationTimer,
    FlushReason,
    InactivityTimer,
    VoicemailHandler,
)
from worker.control import RuntimeCallControl
from worker.flow import FlowRuntimeUnavailable
from worker.internal_api import (
    ClaimRequest,
    InternalApiClient,
    RuntimeConfig,
    SipAttributes,
)
from worker.metrics import (
    EventPoster,
    EventRecorder,
    LatencyTracker,
    MetricsBridge,
    TurnRecord,
    UsageMeters,
)
from worker.pipeline import (
    GENERATED_GREETING_INSTRUCTION,
    OverrideManager,
    SessionComponents,
    SessionPlan,
    build_agent,
    build_components,
    build_session,
    plan_session,
    vendor_error_diagnostic,
    voicemail_tool,
)
from worker.settings import WorkerSettings, get_settings
from worker.telephony import TelephonyUnavailable, dtmf_code, sip_attributes
from worker.tools import ToolActivity
from worker.turn_detection import DigitAwareTurnDetector

log = logging.getLogger("callwright.worker")

SIP_CHANNELS = frozenset({"sip_inbound", "whatsapp"})
SYSTEM_EVENT_FOR_REASON = {
    "inactivity": "silence_timeout",
    "max_duration_reached": "max_duration",
    "insufficient_credit": "credit_exhausted",
    "voicemail_reached": "voicemail_detected",
}


def parse_dispatch_metadata(raw: str | None) -> dict[str, Any]:
    """Dispatch metadata is JSON (R1); anything else is passed to the API as ``{"raw": ...}``."""
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except ValueError:
        return {"raw": raw}
    return value if isinstance(value, dict) else {"raw": raw}


def make_api_client(settings: WorkerSettings) -> InternalApiClient:
    return InternalApiClient(
        settings.internal_api_url,
        settings.service_token.get_secret_value(),
        timeout_s=settings.http_timeout_s,
        max_attempts=settings.events_max_attempts,
        backoff_base_s=settings.events_backoff_base_s,
    )


# --------------------------------------------------------------------------------------------
# Live call


class LiveCall:
    """One claimed call on a LiveKit room. Implements ``CallBackend`` for the control."""

    def __init__(
        self,
        ctx: Any,
        api: InternalApiClient,
        settings: WorkerSettings,
        call_id: str,
        runtime: RuntimeConfig,
        registry: AdapterRegistry | None = None,
    ) -> None:
        self.ctx = ctx
        self.api = api
        self.settings = settings
        self.call_id = call_id
        self.runtime = runtime
        self.registry = registry or AdapterRegistry()
        self.clock = AsyncioClock()
        self.meters = UsageMeters()
        self.recorder = EventRecorder(self.meters, monotonic=time.monotonic)
        self.tracker = LatencyTracker()
        self.poster = EventPoster(
            call_id,
            self.recorder,
            api,
            on_end_call=self._on_control_end,
            interval_s=float(runtime.heartbeat_interval_s or settings.heartbeat_interval_s),
            before_flush=self._update_time_meters,
        )
        self.plan: SessionPlan | None = None
        self.overrides: OverrideManager | None = None
        self.components: SessionComponents | None = None
        self.control: RuntimeCallControl | None = None
        self.session: Any = None
        self.agent: Any = None
        self.caller_identity: str | None = None
        self.connected_at: float | None = None
        self.inactivity: InactivityTimer | None = None
        self.duration: DurationTimer | None = None
        self.dtmf: DtmfCollector | None = None
        self.voicemail: VoicemailHandler | None = None
        self.background: Any = None
        self.session_span: Any = None
        self._agent_state = "initializing"
        self._ended = asyncio.Event()
        self._swap_pending = False
        self._tasks: set[asyncio.Task[Any]] = set()
        self._extra_tools: list[Any] = []
        self._extra_instructions = ""

    # helpers ---------------------------------------------------------------

    def _spawn(self, coro: Any) -> None:
        task = asyncio.ensure_future(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    def _models(self, kind: Kind) -> tuple[str, str | None]:
        assert self.overrides is not None
        spec = self.overrides.current[kind]
        return spec.provider, spec.model

    def _update_time_meters(self) -> None:
        if self.plan is None or self.connected_at is None:
            return
        nc = self.components.nc if self.components is not None else None
        if nc is not None and hasattr(nc, "processed_ms"):
            # Adapters that report processed audio (Sanas) meter only audio they transformed;
            # a pass-through engine meters nothing, so an unapplied NC is never billed.
            audio_ms = float(nc.processed_ms) if getattr(nc, "applied", True) else 0.0
        else:
            audio_ms = (time.monotonic() - self.connected_at) * 1000.0
        if audio_ms > 0:
            self.meters.set_nc(self.plan.nc.provider, self.plan.nc.model or "", audio_ms)

    def _warn_nc_passthrough(self, plan: SessionPlan) -> None:
        nc = self.components.nc if self.components is not None else None
        if nc is not None and getattr(nc, "applied", True) is False:
            reason = getattr(nc, "passthrough_reason", None) or "engine_unavailable"
            self.recorder.warning(
                "nc_passthrough",
                component="nc",
                provider=plan.nc.provider,
                detail=f"{reason}: caller audio is not noise-cancelled and not metered",
            )

    def _on_tts_text(self, text: str) -> None:
        provider, model = self._models("tts")
        self.meters.add_tts(provider, model, len(text))

    async def _fail(self, diagnostic: str) -> None:
        """Before connection: the call never ran (``failed``, no billing)."""
        self.recorder.status("failed", disconnect_reason="error", diagnostic=diagnostic)
        await self.poster.flush(with_usage=False)
        await self._close_room()

    async def _close_room(self) -> None:
        with contextlib.suppress(Exception):
            await self.ctx.delete_room()
        self.ctx.shutdown(reason="call ended")
        self._ended.set()

    # CallBackend -----------------------------------------------------------

    async def speak(self, text: str, allow_interruptions: bool) -> None:
        if self.session is not None:
            self.session.say(text, allow_interruptions=allow_interruptions)

    async def send_dtmf(self, digits: str) -> None:
        for digit in digits:
            await self.ctx.room.local_participant.publish_dtmf(code=dtmf_code(digit), digit=digit)
            await asyncio.sleep(0.1)

    async def end(self, reason: str, diagnostic: str | None) -> None:
        for timer in (self.inactivity, self.duration):
            if timer is not None:
                timer.stop()
        if self.dtmf is not None:
            self.dtmf.close()
        system = SYSTEM_EVENT_FOR_REASON.get(reason)
        if system:
            self.recorder.system(system, diagnostic)
        if diagnostic and diagnostic.startswith("vendor_error"):
            self.recorder.system("vendor_error", diagnostic)
        if self.session is not None:
            with contextlib.suppress(Exception):
                self.session.interrupt()
        self.recorder.status("ended", disconnect_reason=reason, diagnostic=diagnostic)
        await self.poster.stop()
        if self.background is not None:
            with contextlib.suppress(Exception):
                await self.background.aclose()
        if self.session is not None:
            with contextlib.suppress(Exception):
                await self.session.aclose()
        if self.session_span is not None:
            self.session_span.set_attribute("call.disconnect_reason", reason)
            if diagnostic:
                self.session_span.set_attribute("call.diagnostic", diagnostic)
            self.session_span.end()
        await self._close_room()

    async def _on_control_end(self, reason: str) -> None:
        if self.control is not None:
            self._spawn(self.control.hang_up(reason))

    def _hang_up_soon(self, reason: str, diagnostic: str | None = None) -> None:
        if self.control is not None and not self.control.ending:
            self._spawn(self.control.hang_up(reason, diagnostic=diagnostic))

    # turn boundary swaps (FR-046) -------------------------------------------

    def _request_swap(self) -> None:
        self._swap_pending = True
        if self._agent_state in ("listening", "idle"):
            self._apply_swap()

    def _apply_swap(self) -> None:
        if not self._swap_pending or self.overrides is None or self.session is None:
            return
        self._swap_pending = False
        swap = self.overrides.apply_pending()
        if swap is None or self.components is None:
            return
        creds = self.settings.vendor_credentials()
        for kind in swap.kinds:
            spec = swap.specs[kind]
            self.components.set(kind, self.registry.build(spec, creds.get(spec.provider, {})))
        plan = self.overrides.plan_for_current()
        assert self.control is not None
        self.agent = build_agent(
            plan,
            self.runtime,
            self.control,
            on_tts_text=self._on_tts_text,
            extra_tools=self._extra_tools,
            extra_instructions=self._extra_instructions,
            stt=self.components.stt,
            llm=self.components.llm,
            tts=self.components.tts,
            chat_ctx=self.agent.chat_ctx if self.agent is not None else None,
        )
        self.session.update_agent(self.agent)

    # session events --------------------------------------------------------

    def _wire(self, session: Any, plan: SessionPlan) -> None:
        bridge = MetricsBridge(self.tracker, self.meters, self._models)
        session.on("metrics_collected", lambda ev: bridge.on_metrics(ev.metrics))
        session.on("user_state_changed", self._on_user_state)
        session.on("agent_state_changed", self._on_agent_state)
        session.on("conversation_item_added", self._on_item)
        session.on("error", lambda ev: self._on_error(ev, plan))
        room = self.ctx.room
        room.on("participant_disconnected", self._on_participant_left)
        room.on("sip_dtmf_received", self._on_dtmf)

    def _on_user_state(self, ev: Any) -> None:
        if ev.new_state == "speaking":
            self.tracker.user_speech_started()
            if self.inactivity:
                self.inactivity.activity()
                self.inactivity.busy_begin("caller")
            if self.voicemail:
                self.voicemail.caller_speech_started()
        elif ev.old_state == "speaking":
            self.tracker.user_speech_ended(ev.created_at)
            if self.inactivity:
                self.inactivity.busy_end("caller")
            if self.voicemail:
                self.voicemail.caller_speech_ended()

    def _on_agent_state(self, ev: Any) -> None:
        self._agent_state = ev.new_state
        timer = self.inactivity
        if ev.new_state == "thinking":
            if timer:
                timer.busy_begin("agent")
            current = self.tracker.current
            if current is None or current.agent_first_audio_at is not None:
                self.tracker.begin_turn()
        elif ev.new_state == "speaking":
            if timer:
                timer.activity()
                timer.busy_begin("agent")
            self.tracker.agent_audio_started(ev.created_at)
        elif ev.new_state in ("listening", "idle"):
            if timer:
                timer.busy_end("agent")
            self._apply_swap()

    def _on_item(self, ev: Any) -> None:
        item = ev.item
        role = getattr(item, "role", None)
        text = getattr(item, "text_content", None) or ""
        offset = self.recorder.offset_ms()
        if role == "user":
            self.recorder.message(
                "user",
                text,
                started_ms=offset,
                ended_ms=offset,
                confidence=getattr(item, "transcript_confidence", None),
                source="voice",
            )
        elif role == "assistant":
            turn: TurnRecord | None = self.tracker.current
            if turn is not None:
                turn.interrupted = bool(getattr(item, "interrupted", False))
                turn.text = turn.played_text = text
                self.recorder.turn(turn)
            self.recorder.message(
                "agent",
                text,
                started_ms=offset,
                ended_ms=offset,
                turn_index=turn.turn_index if turn else None,
                interrupted=turn.interrupted if turn else False,
            )

    def _on_error(self, ev: Any, plan: SessionPlan) -> None:
        error = ev.error
        diagnostic = vendor_error_diagnostic(ev.source, plan)
        kind, _, provider = diagnostic.removeprefix("vendor_error:").partition("/")
        recoverable = bool(getattr(error, "recoverable", False))
        self.recorder.warning(
            "vendor_retry" if recoverable else "vendor_error",
            component=kind if kind in ("stt", "llm", "tts") else "runtime",
            provider=provider,
            detail=str(getattr(error, "error", error))[:2000],
            level="warning" if recoverable else "error",
        )
        if not recoverable:
            self._hang_up_soon("error", diagnostic)

    def _on_participant_left(self, participant: Any) -> None:
        if participant.identity == self.caller_identity:
            self._hang_up_soon("user_hangup")

    def _on_dtmf(self, ev: Any) -> None:
        if self.inactivity:
            self.inactivity.activity()
        if self.dtmf is not None:
            with contextlib.suppress(ValueError):
                self.dtmf.add(ev.digit)

    def _on_dtmf_flush(self, digits: str, reason: FlushReason) -> None:
        self.recorder.dtmf(digits, "received", reason)
        offset = self.recorder.offset_ms()
        self.recorder.message("user", digits, started_ms=offset, ended_ms=offset, source="keypad")
        if self.session is not None:
            self.tracker.user_speech_ended(time.time())
            self.session.generate_reply(user_input=digits)

    # run -------------------------------------------------------------------

    async def run(self) -> None:
        runtime = self.runtime
        try:
            plan = plan_session(runtime, self.registry)
        except UnsupportedVendor as exc:
            await self._fail(exc.diagnostic)
            return
        except UnsupportedLanguage as exc:
            await self._fail(f"unsupported_language:stt/{exc.provider}/{exc.language}")
            return
        self.plan = plan
        for clamp in plan.behavior.notes:
            self.recorder.warning(
                "config_value_clamped",
                component="runtime",
                detail=f"{clamp.path} {clamp.value} -> {clamp.clamped_to}",
            )
        for warning in plan.warnings:
            self.recorder.warning(warning.code, component="runtime", detail=warning.detail)

        self.overrides = OverrideManager(
            plan, self.registry, runtime.controls, on_system_event=self.recorder.system
        )
        self.control = RuntimeCallControl(
            self.call_id,
            self.recorder,
            self,
            overrides=self.overrides,
            room=self.ctx.room,
            on_overrides_staged=self._request_swap,
        )
        behavior = plan.behavior
        extra_tools: list[Any] = []
        extra_instructions = ""
        if runtime.direction == "outbound" and behavior.voicemail.enabled:
            self.voicemail = VoicemailHandler(
                self.clock,
                behavior.voicemail,
                hang_up=lambda: self._hang_up_soon("voicemail_reached"),
                speak_message=self._leave_voicemail,
            )
            extra_tools.append(voicemail_tool(self._report_machine))
            extra_instructions = VOICEMAIL_INSTRUCTION
        self._extra_tools = extra_tools
        self._extra_instructions = extra_instructions
        try:
            self.components = build_components(
                plan, self.registry, self.settings.vendor_credentials()
            )
            self.agent = build_agent(
                plan,
                runtime,
                self.control,
                on_tts_text=self._on_tts_text,
                extra_tools=extra_tools,
                extra_instructions=extra_instructions,
            )
        except FlowRuntimeUnavailable as exc:
            await self._fail(exc.diagnostic)
            return

        turn_detector = None
        if plan.turn_detection == "semantic":
            from livekit.plugins.turn_detector.multilingual import MultilingualModel

            # R4: one model for every language (it ignores STT punctuation, the English model
            # does not); a trailing digit string is held as unfinished.
            turn_detector = DigitAwareTurnDetector(MultilingualModel())
        self.session = build_session(
            plan,
            self.components,
            vad=self.ctx.proc.userdata.get("vad"),
            turn_detector=turn_detector,
            retry_window_s=self.settings.vendor_retry_window_s,
        )
        self._wire(self.session, plan)
        self.poster.start()

        participant = await self._await_caller()
        if participant is None:
            return
        self.caller_identity = participant.identity
        await self._connected(plan)
        await self._ended.wait()

    async def run_safely(self) -> None:
        """``run`` with a last-resort handler: a crash still ends the call with a diagnostic."""
        try:
            await self.run()
        except Exception:
            log.exception("call %s crashed", self.call_id)
            if self.connected_at is None:
                await self._fail("worker_exception")
            elif self.control is not None:
                await self.control.hang_up("error", diagnostic="worker_exception")

    async def _await_caller(self) -> Any:
        runtime = self.runtime
        if runtime.channel == "sip_outbound":
            if runtime.outbound_dial is None:
                await self._fail("outbound-dial-missing")
                return None
            try:
                from worker.telephony import dial_outbound

                return await dial_outbound(self.ctx, runtime.outbound_dial)
            except TelephonyUnavailable as exc:
                await self._fail(exc.diagnostic)
                return None
        try:
            return await asyncio.wait_for(
                self.ctx.wait_for_participant(), timeout=runtime.caller_join_timeout_s
            )
        except TimeoutError:
            await self._fail("caller_never_joined")
            return None

    async def _connected(self, plan: SessionPlan) -> None:
        assert self.components is not None and self.control is not None
        self.connected_at = time.monotonic()
        self.recorder.connected()
        self.tracker.connected(time.time())
        self.recorder.status("in_progress")
        self._warn_nc_passthrough(plan)

        behavior = plan.behavior
        self.inactivity = InactivityTimer(
            self.clock, behavior.end_on_silence_s, lambda: self._hang_up_soon("inactivity")
        )
        self.duration = DurationTimer(
            self.clock, behavior.max_duration_s, lambda: self._hang_up_soon("max_duration_reached")
        )
        if behavior.dtmf.enabled:
            self.dtmf = DtmfCollector(self.clock, behavior.dtmf, self._on_dtmf_flush)
        if self.voicemail is not None:
            self.voicemail.answered()

        self.session_span = telemetry.start_span(
            "session",
            {
                "call.channel": self.runtime.channel,
                "call.direction": self.runtime.direction,
                "vendor.stt": f"{plan.stt.provider}/{plan.stt.model}",
                "vendor.llm": f"{plan.llm.provider}/{plan.llm.model}",
                "vendor.tts": f"{plan.tts.provider}/{plan.tts.model}",
                "vendor.nc": f"{plan.nc.provider}/{plan.nc.model}",
                "turn_detection": plan.turn_detection,
            },
        )
        # Session tasks inherit this context, so turn and tool spans nest under ``session``.
        with telemetry.use_span(self.session_span):
            await self._start_session(plan)

    async def _start_session(self, plan: SessionPlan) -> None:
        from livekit.agents import room_io

        assert self.components is not None and self.inactivity and self.duration
        await self.session.start(
            agent=self.agent,
            room=self.ctx.room,
            room_options=room_io.RoomOptions(
                audio_input=room_io.AudioInputOptions(
                    noise_cancellation=self.components.nc, frame_size_ms=INPUT_FRAME_MS
                ),
                participant_identity=self.caller_identity or "",
                close_on_disconnect=False,
            ),
        )
        self.inactivity.start()
        self.duration.start()
        await self._start_background(plan)

        if plan.start_speaker == "agent":
            self.tracker.begin_turn(greeting=True)
            if plan.greeting:
                self.session.say(plan.greeting)
            else:
                self.session.generate_reply(instructions=GENERATED_GREETING_INSTRUCTION)

    def _report_machine(self) -> bool:
        if self.voicemail is None:
            return False
        detected = self.voicemail.report_machine()
        if detected and self.control is not None:
            self.control.report_tool(ToolActivity(VOICEMAIL_TOOL_NAME, output="detected"))
        return detected

    def _leave_voicemail(self, message: str) -> None:
        async def run() -> None:
            handle = self.session.say(message, allow_interruptions=False)
            await handle
            self._hang_up_soon("voicemail_reached")

        self._spawn(run())

    async def _start_background(self, plan: SessionPlan) -> None:
        if plan.background is None:
            return
        import tempfile
        from pathlib import Path

        import httpx

        from worker.audio import BackgroundAudioCache, build_player

        local = None
        if plan.background.kind == "upload":
            cache = BackgroundAudioCache(Path(tempfile.gettempdir()) / "callwright-ambience")
            async with httpx.AsyncClient(timeout=10.0) as http:
                local = await cache.fetch(plan.background, http)
            if local is None:
                self.recorder.warning(
                    "background_audio_unavailable",
                    component="runtime",
                    detail=f"could not download {plan.background.ref}",
                )
                return
        try:
            self.background = build_player(plan.background, local)
            await self.background.start(room=self.ctx.room, agent_session=self.session)
        except Exception as exc:
            self.recorder.warning(
                "background_audio_unavailable", component="runtime", detail=str(exc)[:2000]
            )


# --------------------------------------------------------------------------------------------
# Job entry


async def claim_job(ctx: Any, api: InternalApiClient) -> tuple[str, RuntimeConfig | None, Any]:
    metadata = parse_dispatch_metadata(getattr(ctx.job, "metadata", None))
    sip: SipAttributes | None = None
    if metadata.get("channel") in SIP_CHANNELS:
        participant = await ctx.wait_for_participant()
        sip = sip_attributes(dict(participant.attributes), participant.identity)
    response = await api.claim(
        ClaimRequest(
            job_id=ctx.job.id,
            room_name=ctx.room.name,
            worker_id=str(ctx.worker_id),
            dispatch_metadata=metadata,
            sip=sip,
        )
    )
    return response.call_id, response.runtime if response.admitted else None, response.refusal


async def job_entry(ctx: Any, registry: AdapterRegistry | None = None) -> None:
    settings = get_settings()
    api = make_api_client(settings)
    attrs = {"livekit.job_id": ctx.job.id, "livekit.room": ctx.room.name}
    with telemetry.call_scope(None), telemetry.span("call", attrs) as call_span:
        try:
            await ctx.connect()
            call_id, runtime, refusal = await claim_job(ctx, api)
            telemetry.set_call_id(call_id, call_span)
            call_span.set_attribute("call.admitted", runtime is not None)
            if runtime is None:
                # Refused (inbound admission) calls hang up without speaking (R2).
                log.info("call %s refused: %s", call_id, refusal)
                with contextlib.suppress(Exception):
                    await ctx.delete_room()
                ctx.shutdown(reason="refused")
                return
            call = LiveCall(ctx, api, settings, call_id, runtime, registry)
            await call.run_safely()
            if call.control is not None and call.control.disconnect_reason:
                call_span.set_attribute("call.disconnect_reason", call.control.disconnect_reason)
        finally:
            await api.aclose()
    telemetry.flush()


INPUT_FRAME_MS = 20
"""Caller audio frame size into VAD and STT (framework default 50 ms). Every caller turn ends
somewhere inside a frame, so 50 ms frames add about 25 ms on average before VAD and the STT
hear the end of speech; 20 ms halves the framing cost for a few more frames per second (R4)."""


def prewarm(proc: Any) -> None:
    """Load Silero VAD once per process (R1); the turn-detector model loads with its plugin.

    ``min_silence_duration`` is the R4 floor of every end of turn (0.3 s, not the 0.55 s
    default)."""
    from livekit.plugins import silero

    if not telemetry.enabled():
        telemetry.configure_tracing(get_settings().otel_exporter)
    proc.userdata["vad"] = silero.VAD.load(min_silence_duration=VAD_MIN_SILENCE_S)


def create_server(
    settings: WorkerSettings,
    *,
    entrypoint: Callable[[Any], Awaitable[None]] = job_entry,
    **server_options: Any,
) -> Any:
    """The LiveKit agent server. ``entrypoint`` and ``server_options`` exist for the live
    benchmark, which runs the same server with fake vendors and an ephemeral health port."""
    # Importing the plugin registers the turn-detector model for download and inference.
    import livekit.plugins.turn_detector.multilingual  # noqa: F401
    from livekit.agents import AgentServer

    options: dict[str, Any] = {"port": settings.health_port}
    if settings.num_idle_processes is not None:
        options["num_idle_processes"] = settings.num_idle_processes
    if settings.load_threshold is not None:
        options["load_threshold"] = settings.load_threshold
    options.update(server_options)
    server = AgentServer(
        setup_fnc=prewarm,
        ws_url=settings.livekit_url,
        api_key=settings.livekit_api_key.get_secret_value(),
        api_secret=settings.livekit_api_secret.get_secret_value(),
        **options,
    )
    server.rtc_session(entrypoint, agent_name=settings.agent_name)
    return server


def run_textsim() -> int:
    """``role=textsim`` (text-mode simulations, 008). Not delivered in 003."""
    log.error("WORKER_ROLE=textsim is delivered by 008-testing-simulation")
    return 2


def main() -> int:
    logging.basicConfig(level=logging.INFO)
    settings = get_settings()
    if settings.role == "textsim":
        return run_textsim()
    from livekit.agents import cli

    cli.run_app(create_server(settings))
    return 0


if __name__ == "__main__":
    sys.exit(main())
