"""Worker entry point. ``WORKER_ROLE=live`` joins LiveKit rooms; ``textsim`` runs 008's text
simulations (``worker.textsim.entry``, an arq consumer; command-line arguments are ignored).

Live job sequence (003 plan, research R1, R2):

1. The dispatch carries ``{"call_id": ...}`` (web, outbound) or ``{"channel", "route_ref"}``
   (SIP inbound, WhatsApp; 010). The worker claims the job at ``POST /v1/internal/calls/claim``
   and receives the frozen :class:`RuntimeConfig`, or a refusal (hang up without speaking).
2. :func:`worker.pipeline.plan_session` resolves vendors; unsupported vendors or a flow agent
   without a runnable compiled flow fail the call with a diagnostic.
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
import importlib
import json
import logging
import sys
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from typing import Any

from callwright_contract import diagnostics as diag
from callwright_contract.adapters import Kind
from callwright_contract.calls import (
    INBOUND_SIP_CHANNELS,
    PHONE_CHANNELS,
    ControlReason,
    DisconnectReason,
    SystemEvent,
)
from callwright_contract.data_channel import LATENCY_TOPIC
from callwright_contract.protocol import (
    DISPATCH_CHANNEL,
    ClaimRequest,
    FlushReason,
    RuntimeConfig,
    SipAttributes,
)

from worker import telemetry
from worker.adapters.registry import (
    AdapterRegistry,
    UnsupportedLanguage,
    UnsupportedVendor,
    VendorSpec,
)
from worker.agent import GENERATED_GREETING_INSTRUCTION, SessionPlan
from worker.audio import PronunciationTransform, scale_frame
from worker.call_behavior import (
    GOODBYE_HANGUP_DELAY_S,
    SILENCE_CHECK_INS,
    SILENCE_GOODBYE,
    VAD_MIN_SILENCE_S,
    VOICEMAIL_INSTRUCTION,
    VOICEMAIL_TOOL_NAME,
    AsyncioClock,
    DtmfCollector,
    DurationTimer,
    InactivityTimer,
    VoicemailHandler,
    ends_with_goodbye,
)
from worker.control import RuntimeCallControl
from worker.flow import FlowComponents, FlowRunner, FlowRuntimeUnavailable
from worker.flow.runtime import CallwrightFlowRunner
from worker.internal_api import InternalApiClient
from worker.language import translate_greeting, translated_greeting_instruction
from worker.metrics import (
    EventPoster,
    EventRecorder,
    LatencyTracker,
    MetricsBridge,
    TurnRecord,
    UsageMeters,
    latency_payload,
)
from worker.pipeline import (
    OverrideManager,
    SessionComponents,
    build_agent,
    build_components,
    build_session,
    failed_vendor,
    plan_session,
    voicemail_tool,
)
from worker.settings import WorkerSettings, get_settings
from worker.telephony import (
    DialFailed,
    dial_outbound,
    dtmf_code,
    play_ringback,
    ring_phase,
    sip_attributes,
)
from worker.tools import ToolActivity
from worker.tools.registry import CallTools, prepare_call_tools
from worker.tools.transfer import DESTINATION_IDENTITY, LiveKitTransferBackend
from worker.turn_detection import DigitAwareTurnDetector

log = logging.getLogger("callwright.worker")

# A hang-up (end_call, a flow End node) waits for a caller who is still talking: up to
# CALLER_QUIET_MAX_WAIT_S for CALLER_QUIET_S without transcribed words (``LiveCall.caller_quiet``).
CALLER_QUIET_S = 1.0
CALLER_QUIET_MAX_WAIT_S = 2.0
# The session closes in well under a second once nothing inside it waits on the close; the cap
# only keeps a vendor that never answers its close from holding the room open.
SESSION_CLOSE_TIMEOUT_S = 10.0
# The flow runtime of this worker process (004); calls release their flow state when they end.
FLOW_RUNNER: FlowRunner = CallwrightFlowRunner()
SYSTEM_EVENT_FOR_REASON: dict[DisconnectReason, SystemEvent] = {
    "inactivity": "silence_timeout",
    "max_duration_reached": "max_duration",
    "insufficient_credit": "credit_exhausted",
    "voicemail_reached": "voicemail_detected",
}


def record_ending(
    recorder: EventRecorder, reason: DisconnectReason, diagnostic: str | None
) -> None:
    """The system lines and final status of a call; the test harness ends calls through it too."""
    system = SYSTEM_EVENT_FOR_REASON.get(reason)
    if system:
        recorder.system(system, diagnostic)
    if diagnostic and diag.parse(diagnostic).code == diag.VENDOR_ERROR:
        recorder.system("vendor_error", diagnostic)
    recorder.status("ended", disconnect_reason=reason, diagnostic=diagnostic)


def parse_dispatch_metadata(raw: str | None) -> dict[str, Any]:
    """Dispatch metadata is JSON (R1); anything else is passed to the API as ``{"raw": ...}``."""
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except ValueError:
        return {"raw": raw}
    return value if isinstance(value, dict) else {"raw": raw}


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
        *,
        flows: FlowRunner = FLOW_RUNNER,
        extra_tools: Sequence[Any] = (),
    ) -> None:
        self.ctx = ctx
        self.api = api
        self.settings = settings
        self.call_id = call_id
        self.runtime = runtime
        self.registry = registry or AdapterRegistry()
        self.flows = flows
        self.tools: CallTools | None = None
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
        # Digits handed to the session as a keypad turn: the session echoes them back as a user
        # conversation item, which must not become a second ("voice") caller line.
        self._keypad_echo: str | None = None
        self.voicemail: VoicemailHandler | None = None
        self.background: Any = None
        self.session_span: Any = None
        self._agent_state = "initializing"
        self._ended = asyncio.Event()
        self._swap_pending = False
        self._tasks: set[asyncio.Task[Any]] = set()
        self._extra_tools: list[Any] = list(extra_tools)
        self._extra_instructions = ""
        self._goodbye_timer: asyncio.TimerHandle | None = None
        self._teardown: asyncio.Future[None] | None = None
        # The caller's last words (interim or final transcript) and whether voice activity
        # detection hears them now (``caller_quiet``).
        self._caller_heard_at = float("-inf")
        self._caller_speaking = False
        # 012: the fixed greeting translated into the caller's saved language.
        self._greeting_text: str | None = None

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
        if self.session_span is not None:
            self.session_span.set_attribute("call.diagnostic", diagnostic)
            self.session_span.end()
        await self.poster.flush(with_usage=False)
        await self._close_room()

    async def _close_room(self, *, keep: bool = False) -> None:
        """Delete the room, or only leave it when a warm transfer left caller and destination
        talking in it (005)."""
        try:
            if keep:
                await self.ctx.room.disconnect()
            else:
                await self.ctx.delete_room()
        except Exception as exc:  # the job still shuts down
            log.warning("room not closed for %s: %r", self.call_id, exc)
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

    async def end(self, reason: DisconnectReason, diagnostic: str | None) -> None:
        """Stop the timers at once and close the call in a task of its own.

        Hang-ups usually come from inside the session: end_call and transfer tools, a flow's
        End node (a tool call or a step agent's ``on_enter``). Closing the session waits for
        every running speech task, including the one that asked for the hang-up, so awaiting
        the close here deadlocked: LiveKit cancelled the tool after its interruption timeout,
        the close never finished, the room stayed open and the job was killed after
        ``AgentSession.aclose()`` timed out at shutdown. The teardown task runs after the
        caller's own code has returned (so its last events, such as end_call's ``tool_call``,
        are recorded before the final status); ``run`` waits for it through ``_ended``."""
        for timer in (self.inactivity, self.duration):
            if timer is not None:
                timer.stop()
        if self.dtmf is not None:
            self.dtmf.close()
        self._cancel_goodbye()
        if self._teardown is None:
            self._teardown = asyncio.ensure_future(self._close_call(reason, diagnostic))

    async def _close_call(self, reason: DisconnectReason, diagnostic: str | None) -> None:
        """Post the final status with usage, close the session and the room (``end``)."""
        try:
            if self.session is not None:
                try:
                    self.session.interrupt()
                except Exception as exc:  # the final status is posted regardless
                    log.warning("speech not interrupted for %s: %r", self.call_id, exc)
            record_ending(self.recorder, reason, diagnostic)
            await self.poster.stop()
            if self.background is not None:
                try:
                    await self.background.aclose()
                except Exception as exc:
                    log.warning("ambience not closed for %s: %r", self.call_id, exc)
            if self.session is not None:
                try:
                    await asyncio.wait_for(self.session.aclose(), SESSION_CLOSE_TIMEOUT_S)
                except Exception as exc:  # a stuck close must not keep the room open
                    log.warning("session close failed for %s: %r", self.call_id, exc)
            if self.session_span is not None:
                self.session_span.set_attribute("call.disconnect_reason", reason)
                if diagnostic:
                    self.session_span.set_attribute("call.diagnostic", diagnostic)
                self.session_span.end()
            self.flows.release(self.call_id)
            if self.tools is not None:
                await self.tools.aclose()
        finally:
            await self._close_room(keep=reason == "call_transfer" and self._destination_in_room())

    def _destination_in_room(self) -> bool:
        participants = self.ctx.room.remote_participants.values()
        return any(p.identity == DESTINATION_IDENTITY for p in participants)

    def _transfer_backend(self) -> LiveKitTransferBackend | None:
        """Transfers (005) on SIP calls through the LiveKit server API."""
        runtime = self.runtime
        if runtime.channel not in PHONE_CHANNELS:
            return None
        settings = self.settings

        def synthesize(text: str) -> Any:
            assert self.components is not None
            return self.components.tts.synthesize(text)

        return LiveKitTransferBackend(
            url=settings.livekit_url,
            api_key=settings.livekit_api_key.get_secret_value(),
            api_secret=settings.livekit_api_secret.get_secret_value(),
            room_name=self.ctx.room.name,
            caller_identity=lambda: self.caller_identity,
            trunk_id=(runtime.outbound_dial.sip_trunk_id if runtime.outbound_dial else None)
            or settings.sip_outbound_trunk_id
            or None,
            synthesize=synthesize,
        )

    async def _on_control_end(self, reason: ControlReason) -> None:
        if self.control is not None:
            self._spawn(self.control.hang_up(reason))

    def _hang_up_soon(self, reason: DisconnectReason, diagnostic: str | None = None) -> None:
        if self.control is not None and not self.control.ending:
            self._spawn(self.control.hang_up(reason, diagnostic=diagnostic))

    # turn boundary swaps (FR-046) -------------------------------------------

    def request_swap(self) -> None:
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
        try:
            built = {
                kind: self.registry.build(spec, creds.get(spec.provider, {}))
                for kind, spec in ((k, swap.specs[k]) for k in swap.kinds)
            }
        except UnsupportedVendor as exc:
            # A vendor this deployment has no key for: keep the current components.
            self.recorder.warning(
                "override_rejected", component=exc.kind, provider=exc.provider, detail=str(exc)
            )
            return
        for kind, component in built.items():
            self.components.set(kind, component)
        plan = self.overrides.plan_for_current()
        assert self.control is not None and self.tools is not None
        if plan.agent_type == "flow":
            # A flow keeps its place: the current node's agent is rebuilt with the new plan and
            # components (rebuilding the entry agent would restart the flow).
            components = {k: self.components.get(k) for k in ("stt", "llm", "tts")}
            agent = self.flows.rebuild(self.call_id, plan, components)
            if agent is not None:
                self.session.update_agent(agent)
            return
        self.agent = build_agent(
            plan,
            self.runtime,
            self.control,
            self.tools,
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

    def wire(self, session: Any, plan: SessionPlan) -> None:
        bridge = MetricsBridge(self.tracker, self.meters, self._models)
        session.on("metrics_collected", lambda ev: bridge.on_metrics(ev.metrics))
        session.on("user_state_changed", self._on_user_state)
        session.on("agent_state_changed", self._on_agent_state)
        session.on("conversation_item_added", self._on_item)
        session.on("user_input_transcribed", self._on_transcribed)
        session.on("error", lambda ev: self._on_error(ev, plan))
        room = self.ctx.room
        room.on("participant_disconnected", self._on_participant_left)
        room.on("sip_dtmf_received", self._on_dtmf)

    def _on_transcribed(self, ev: Any) -> None:
        if str(getattr(ev, "transcript", "") or "").strip():
            self._caller_heard_at = time.monotonic()

    async def caller_quiet(
        self, quiet_s: float = CALLER_QUIET_S, max_wait_s: float = CALLER_QUIET_MAX_WAIT_S
    ) -> bool:
        """Wait (at most ``max_wait_s``) until the caller is not
        speaking and no words were transcribed in the last ``quiet_s``. At the deadline only
        transcribed words count, so line noise that voice detection hears never keeps a call
        open. Returns immediately in the usual case (the caller finished seconds ago)."""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + max_wait_s
        while True:
            heard = time.monotonic() - self._caller_heard_at < quiet_s
            if not heard and not self._caller_speaking:
                return True
            if loop.time() >= deadline:
                return not heard
            await asyncio.sleep(0.05)

    def _on_user_state(self, ev: Any) -> None:
        self._caller_speaking = ev.new_state == "speaking"
        if ev.new_state == "speaking":
            self._cancel_goodbye()
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
                if not timer.checking_in:  # its own silence check-ins do not reset the count
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
            self._cancel_goodbye()
            if self._keypad_echo is not None and text == self._keypad_echo:
                self._keypad_echo = None  # already recorded as the keypad line
                return
            self.tracker.transcript_final(time.time())
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
                self._publish_latency(turn)
            # The item arrives once playout ends: start the line at the turn's first audio.
            started = offset
            if offset is not None and turn is not None and turn.agent_first_audio_at is not None:
                started = max(0, offset - round((time.time() - turn.agent_first_audio_at) * 1000))
            self.recorder.message(
                "agent",
                text,
                started_ms=started,
                ended_ms=offset,
                turn_index=turn.turn_index if turn else None,
                interrupted=turn.interrupted if turn else False,
            )
            if not (turn and turn.interrupted) and ends_with_goodbye(text):
                self._schedule_goodbye()

    def _publish_latency(self, turn: TurnRecord) -> None:
        """Send the turn's latency split to the room (``cw.turn_latency``) for the browser panel.
        Best effort: a failed publish never affects the call."""
        payload = latency_payload(turn)
        participant = getattr(self.ctx.room, "local_participant", None)
        if payload is None or participant is None:
            return
        data = json.dumps(payload).encode()

        async def publish() -> None:
            try:
                await participant.publish_data(data, reliable=True, topic=LATENCY_TOPIC)
            except Exception as exc:
                log.debug("turn latency not published for %s: %s", self.call_id, exc)

        self._spawn(publish())

    def _on_error(self, ev: Any, plan: SessionPlan) -> None:
        error = ev.error
        kind, provider = failed_vendor(ev.source, plan)
        recoverable = bool(getattr(error, "recoverable", False))
        self.recorder.warning(
            "vendor_retry" if recoverable else diag.VENDOR_ERROR,
            component=kind,
            provider=provider,
            detail=str(getattr(error, "error", error))[:2000],
            level="warning" if recoverable else "error",
        )
        if not recoverable:
            self._hang_up_soon("error", diag.diagnostic(diag.VENDOR_ERROR, kind, provider))

    def _schedule_goodbye(self) -> None:
        """The agent said goodbye: hang up shortly after unless end_call already did or the
        caller starts speaking (``_cancel_goodbye``). No reply from the caller is needed."""
        self._cancel_goodbye()

        def hang_up() -> None:
            self._goodbye_timer = None
            if self.control is not None and not self.control.ending:
                self._spawn(self.control.hang_up("agent_hangup"))

        self._goodbye_timer = asyncio.get_running_loop().call_later(GOODBYE_HANGUP_DELAY_S, hang_up)

    def _cancel_goodbye(self) -> None:
        if self._goodbye_timer is not None:
            self._goodbye_timer.cancel()
            self._goodbye_timer = None

    def _on_participant_left(self, participant: Any) -> None:
        if participant.identity == self.caller_identity:
            self._hang_up_soon("user_hangup")

    def _on_dtmf(self, ev: Any) -> None:
        if self.inactivity:
            self.inactivity.activity()
        if self.dtmf is not None:
            with contextlib.suppress(ValueError):
                self.dtmf.add(ev.digit)

    def on_dtmf_flush(self, digits: str, reason: FlushReason) -> None:
        self.recorder.dtmf(digits, "received", reason)
        offset = self.recorder.offset_ms()
        self.recorder.message("user", digits, started_ms=offset, ended_ms=offset, source="keypad")
        if self.session is not None:
            self.tracker.user_speech_ended(time.time())
            self._keypad_echo = digits
            self.session.generate_reply(user_input=digits)

    # run -------------------------------------------------------------------

    async def run(self) -> None:
        runtime = self.runtime
        try:
            plan = plan_session(runtime, self.registry, self.flows)
        except (UnsupportedVendor, UnsupportedLanguage, FlowRuntimeUnavailable) as exc:
            await self._fail(exc.diagnostic)
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
        if (
            plan.llm.provider == "azure_openai"
            and self.settings.azure_openai_falls_back_to_openai()
        ):
            self.recorder.warning(
                "llm_provider_fallback",
                component="llm",
                provider="azure_openai",
                detail=f"Azure OpenAI is not configured; {plan.llm.model} runs on OpenAI",
            )

        self.overrides = OverrideManager(
            plan,
            self.registry,
            runtime.controls,
            runtime.stt_auto_rules,
            on_system_event=self.recorder.system,
        )
        self.control = RuntimeCallControl(
            self.call_id,
            self.recorder,
            self,
            overrides=self.overrides,
            room=self.ctx.room,
            on_overrides_staged=self.request_swap,
        )
        behavior = plan.behavior
        extra_instructions = ""
        if runtime.direction == "outbound" and behavior.voicemail.enabled:
            self.voicemail = VoicemailHandler(
                self.clock,
                behavior.voicemail,
                hang_up=lambda: self._hang_up_soon("voicemail_reached"),
                speak_message=self._leave_voicemail,
            )
            self._extra_tools.append(voicemail_tool(self._report_machine))
            extra_instructions = VOICEMAIL_INSTRUCTION
        self._extra_instructions = extra_instructions
        self.tools = await prepare_call_tools(
            runtime, self.control, self.api, transfer_backend=self._transfer_backend()
        )
        try:
            self.components = build_components(
                plan, self.registry, self.settings.vendor_credentials()
            )
            self.agent = build_agent(
                plan,
                runtime,
                self.control,
                self.tools,
                flows=self.flows,
                on_tts_text=self._on_tts_text,
                extra_tools=self._extra_tools,
                extra_instructions=extra_instructions,
                flow_components=self._flow_components(),
            )
        except (FlowRuntimeUnavailable, UnsupportedVendor) as exc:
            # UnsupportedVendor here is a catalog vendor without a key (VendorNotConfigured).
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
        self.wire(self.session, plan)
        self.poster.start()

        # The session (agent track, STT socket, noise cancellation) and a fixed greeting's audio
        # are ready while the caller is still joining, so the greeting plays as soon as the
        # caller subscribes; agent audio output waits for that subscription.
        greeting_audio = self._presynthesize_greeting(plan)
        self.session_span = self._open_session_span(plan)
        with telemetry.use_span(self.session_span):
            await self._start_session()
        participant = await self._await_caller()
        if participant is None:
            return
        self.caller_identity = participant.identity
        self.session.room_io.set_participant(participant.identity)
        await self._connected(plan, greeting_audio)
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
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(self._ended.wait(), SESSION_CLOSE_TIMEOUT_S + 15)

    async def _await_caller(self) -> Any:
        runtime = self.runtime
        if runtime.channel == "sip_outbound":
            if runtime.outbound_dial is None:
                await self._fail(diag.OUTBOUND_DIAL_MISSING)
                return None
            try:
                return await dial_outbound(self.ctx, runtime.outbound_dial, self.recorder)
            except DialFailed as exc:
                await self._not_answered(exc)
                return None
        try:
            participant = await asyncio.wait_for(
                self.ctx.wait_for_participant(), timeout=runtime.caller_join_timeout_s
            )
        except TimeoutError:
            await self._fail(diag.CALLER_NEVER_JOINED)
            return None
        if runtime.channel in INBOUND_SIP_CHANNELS and self.plan is not None:
            # 010 R5: ring for the agent's ring duration before answering; never billed.
            ring_ms = self.plan.behavior.ring_duration_ms
            room = self.ctx.room
            if not await ring_phase(
                room,
                self.recorder,
                ring_ms,
                participant.identity,
                ringback=lambda: play_ringback(room),
            ):
                await self._fail("caller_hung_up_while_ringing")
                return None
        return participant

    async def _not_answered(self, exc: DialFailed) -> None:
        """Outbound busy, no answer or failed (010 R6): never connected, never billed."""
        self.recorder.status(
            exc.status,
            disconnect_reason="error" if exc.status == "failed" else None,
            diagnostic=exc.diagnostic,
            sip_status_code=exc.sip_status_code,
        )
        if self.session_span is not None:
            self.session_span.set_attribute("call.diagnostic", exc.diagnostic)
            self.session_span.end()
        await self.poster.flush(with_usage=False)
        await self._close_room()

    async def _connected(
        self, plan: SessionPlan, greeting_audio: asyncio.Task[list[Any]] | None = None
    ) -> None:
        assert self.components is not None and self.control is not None
        self.connected_at = time.monotonic()
        self.recorder.connected()
        self.tracker.connected(time.time())
        self.recorder.status("in_progress")
        self._warn_nc_passthrough(plan)

        behavior = plan.behavior
        self.inactivity = InactivityTimer(
            self.clock,
            behavior.end_on_silence_s,
            self._end_on_silence,
            on_check_in=self._check_in_on_silence,
        )
        self.duration = DurationTimer(
            self.clock, behavior.max_duration_s, lambda: self._hang_up_soon("max_duration_reached")
        )
        if behavior.dtmf.enabled:
            self.dtmf = DtmfCollector(self.clock, behavior.dtmf, self.on_dtmf_flush)
        if self.voicemail is not None:
            self.voicemail.answered()

        assert self.inactivity and self.duration
        self.inactivity.start()
        self.duration.start()
        with telemetry.use_span(self.session_span):
            await self._start_background(plan)
        if plan.start_speaker == "agent":
            self.tracker.begin_turn(greeting=True)
            if not plan.greeting:
                self.session.generate_reply(instructions=GENERATED_GREETING_INSTRUCTION)
                return
            # A fixed opening often carries disclosures (recorded line, virtual assistant, debt
            # collection notice) that must be heard in full, so the caller cannot talk over it.
            frames = await self._greeting_frames(greeting_audio)
            if plan.greeting_language:
                if frames is None or not self._greeting_text:
                    # Translation not ready: the model writes the same greeting in the language.
                    self.session.generate_reply(
                        instructions=translated_greeting_instruction(
                            plan.greeting, plan.greeting_language
                        ),
                        allow_interruptions=False,
                    )
                    return
                self.session.say(
                    self._greeting_text, allow_interruptions=False, audio=_replay(frames)
                )
                return
            audio = {} if frames is None else {"audio": _replay(frames)}
            self.session.say(plan.greeting, allow_interruptions=False, **audio)

    def _flow_components(self) -> FlowComponents:
        """How 004's node agents build their own LLM, TTS and STT, and report flow timings."""
        creds = self.settings.vendor_credentials()

        def build(spec: VendorSpec) -> Any:
            return self.registry.build(spec, creds.get(spec.provider, {}))

        def timing(key: str, ms: int) -> None:
            turn = self.tracker.current
            if turn is not None:
                setattr(turn, key, ms)

        return FlowComponents(self.registry, build, timing)

    def _open_session_span(self, plan: SessionPlan) -> Any:
        return telemetry.start_span(
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

    def _presynthesize_greeting(self, plan: SessionPlan) -> asyncio.Task[list[Any]] | None:
        """Synthesise a fixed greeting in the background (pronunciation and gain applied, as
        the TTS node would). None when the agent does not open with a fixed line."""
        if plan.start_speaker != "agent" or not plan.greeting or self.components is None:
            return None
        greeting = plan.greeting
        tts = self.components.tts

        async def synthesize() -> list[Any]:
            spoken = greeting
            if plan.greeting_language:
                spoken = await self._translate_greeting(plan, greeting, plan.greeting_language)
                self._greeting_text = spoken
            text = PronunciationTransform(plan.pronunciation).apply(spoken)
            async with tts.synthesize(text) as stream:
                frames = [ev.frame async for ev in stream]
            self._on_tts_text(text)
            if plan.tts_gain != 1.0:
                frames = [scale_frame(f, plan.tts_gain) for f in frames]
            return frames

        return asyncio.ensure_future(synthesize())

    async def _translate_greeting(self, plan: SessionPlan, greeting: str, label: str) -> str:
        """012: the greeting in the caller's language, by the agent's model on its own client
        (metered here; the session's metrics never see it)."""
        creds = self.settings.vendor_credentials()
        llm = self.registry.build(plan.llm, creds.get(plan.llm.provider, {}))

        def meter(input_tokens: int, output_tokens: int) -> None:
            self.meters.add_llm(
                plan.llm.provider,
                plan.llm.model or "",
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            )

        try:
            return await translate_greeting(llm, greeting, label, on_usage=meter)
        finally:
            try:
                await llm.aclose()
            except Exception as exc:
                log.warning("greeting translator not closed for %s: %r", self.call_id, exc)

    async def _greeting_frames(self, task: asyncio.Task[list[Any]] | None) -> list[Any] | None:
        """The pre-synthesised greeting, or None to fall back to live TTS."""
        if task is None:
            return None
        try:
            frames = await task
        except Exception as exc:
            log.warning("greeting pre-synthesis failed for %s: %s", self.call_id, exc)
            return None
        return frames or None

    async def _start_session(self) -> None:
        from livekit.agents import room_io

        assert self.components is not None
        await self.session.start(
            agent=self.agent,
            room=self.ctx.room,
            room_options=room_io.RoomOptions(
                audio_input=room_io.AudioInputOptions(
                    noise_cancellation=self.components.nc, frame_size_ms=INPUT_FRAME_MS
                ),
                close_on_disconnect=False,
            ),
        )

    def _check_in_on_silence(self, stage: int) -> None:
        if self.session is not None and self.control is not None and not self.control.ending:
            self.session.generate_reply(instructions=SILENCE_CHECK_INS[stage])

    def _end_on_silence(self) -> None:
        """Say a short goodbye the caller cannot talk over, then hang up as ``inactivity``."""

        async def run() -> None:
            if self.session is not None:
                try:
                    handle = self.session.generate_reply(
                        instructions=SILENCE_GOODBYE, allow_interruptions=False
                    )
                    await asyncio.wait_for(handle.wait_for_playout(), timeout=15)
                except Exception as exc:  # the call still ends on silence
                    log.warning("silence goodbye not said on %s: %r", self.call_id, exc)
            self._hang_up_soon("inactivity")

        self._spawn(run())

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


async def _replay(frames: list[Any]) -> AsyncIterator[Any]:
    for frame in frames:
        yield frame


# --------------------------------------------------------------------------------------------
# Job entry


async def claim_job(ctx: Any, api: InternalApiClient) -> tuple[str, RuntimeConfig | None, Any]:
    metadata = parse_dispatch_metadata(getattr(ctx.job, "metadata", None))
    sip: SipAttributes | None = None
    if metadata.get(DISPATCH_CHANNEL) in INBOUND_SIP_CHANNELS:
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


async def job_entry(
    ctx: Any, registry: AdapterRegistry | None = None, extra_tools: Sequence[Any] = ()
) -> None:
    settings = get_settings()
    api = InternalApiClient.from_settings(settings)
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
                try:
                    await ctx.delete_room()
                except Exception as exc:
                    log.warning("room of refused call %s not deleted: %r", call_id, exc)
                ctx.shutdown(reason="refused")
                return
            call = LiveCall(ctx, api, settings, call_id, runtime, registry, extra_tools=extra_tools)
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


WARM_IMPORTS = (
    "livekit.plugins.deepgram",
    "livekit.plugins.elevenlabs",
    "livekit.plugins.openai",
    "httpx",
    "anyio",
)


def prewarm(proc: Any) -> None:
    """Load Silero VAD once per process (R1); the turn-detector model loads with its plugin.

    ``min_silence_duration`` is the R4 floor of every end of turn (0.3 s, not the 0.55 s
    default)."""
    from livekit.plugins import silero

    if not telemetry.enabled():
        telemetry.configure_tracing(get_settings().otel_exporter)
    proc.userdata["vad"] = silero.VAD.load(min_silence_duration=VAD_MIN_SILENCE_S)
    # Vendor plugins otherwise load on first use, blocking the event loop for 2 to 3 s at the
    # start of a call (before the greeting on inbound and web calls).
    for module in WARM_IMPORTS:
        with contextlib.suppress(ImportError):
            importlib.import_module(module)


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


def main() -> int:
    logging.basicConfig(level=logging.INFO)
    settings = get_settings()
    if settings.role == "textsim":
        from worker.textsim.entry import main as textsim_main

        return textsim_main()
    from livekit.agents import cli

    cli.run_app(create_server(settings))
    return 0


if __name__ == "__main__":
    sys.exit(main())
