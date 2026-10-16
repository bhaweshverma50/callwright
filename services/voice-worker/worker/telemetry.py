"""OpenTelemetry tracing for the worker (T106, research R21, architecture section 6).

Span tree for one live call (every span carries the ``call_id`` attribute once it is known)::

    call                         job entry to room shutdown (root)
    +- internal_api.claim        POST /v1/internal/calls/claim
    +- session                   caller connected to call ended
    |  +- turn                   caller end of speech to first agent audio, latency attributes
    |  |  +- turn.stt            end of speech to final transcript
    |  |  +- turn.eou            end of speech to end-of-turn decision
    |  |  +- turn.llm            end-of-turn decision to first LLM token
    |  |  +- turn.tts            first LLM token to first TTS audio
    |  +- tool_call              one tool invocation reported through CallControl
    +- internal_api.events       every events post (heartbeat included)

The stage spans are laid out from the per-turn component metrics (the same numbers stored in
``turn`` events), so they show where a turn's time went even when the framework's own spans
are not exported. The livekit-agents spans (``agent_session``, ``user_turn``, ``llm_node``,
``tts_node``, ``function_tool``) join the same trace when tracing is on, and also get
``call_id`` through :class:`CallIdSpanProcessor`.

Exporter (environment, read by :class:`worker.settings.WorkerSettings`):

- ``CALLWRIGHT_OTEL_EXPORTER=none`` (default): nothing is configured, the OpenTelemetry API
  stays a no-op and spans cost close to nothing.
- ``console``: spans printed to stdout (local debugging).
- ``otlp``: OTLP over HTTP; endpoint and headers come from the standard
  ``OTEL_EXPORTER_OTLP_ENDPOINT`` / ``OTEL_EXPORTER_OTLP_TRACES_ENDPOINT`` /
  ``OTEL_EXPORTER_OTLP_HEADERS`` variables.

Conversation content (transcripts, prompts, tool payloads) is stripped from exported
framework spans (``allow_pii=False``); Callwright's own spans carry only ids, counts and
timings.
"""

from __future__ import annotations

import contextvars
import time
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any, Literal

from opentelemetry import context as otel_context
from opentelemetry import trace
from opentelemetry.sdk.trace import ReadableSpan, Span, SpanProcessor, TracerProvider

if TYPE_CHECKING:
    from worker.metrics import TurnRecord

ExporterKind = Literal["none", "console", "otlp"]
SERVICE_NAME = "callwright-voice-worker"
TRACER_NAME = "callwright.worker"
CALL_ID_ATTR = "call_id"

_call_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "callwright_call_id", default=None
)
_provider: trace.TracerProvider | None = None


# --------------------------------------------------------------------------------------------
# Provider setup


class CallIdSpanProcessor(SpanProcessor):
    """Stamps ``call_id`` on every span started while a call is in scope (framework spans too)."""

    def on_start(self, span: Span, parent_context: otel_context.Context | None = None) -> None:
        call_id = _call_id.get()
        if call_id and (span.attributes is None or CALL_ID_ATTR not in span.attributes):
            span.set_attribute(CALL_ID_ATTR, call_id)

    def on_end(self, span: ReadableSpan) -> None:
        return None


def build_provider(
    exporter: ExporterKind, *, resource_attrs: Mapping[str, str] | None = None
) -> TracerProvider | None:
    """A provider with the call-id processor and the chosen exporter, or None for ``none``."""
    if exporter == "none":
        return None
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace.export import (
        BatchSpanProcessor,
        ConsoleSpanExporter,
        SimpleSpanProcessor,
    )

    resource = Resource.create({"service.name": SERVICE_NAME, **dict(resource_attrs or {})})
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(CallIdSpanProcessor())
    if exporter == "console":
        provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
    elif exporter == "otlp":
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    else:
        raise ValueError(f"unknown CALLWRIGHT_OTEL_EXPORTER {exporter!r}")
    return provider


def install(provider: trace.TracerProvider | None, *, framework: bool = True) -> None:
    """Use ``provider`` for Callwright spans (None restores the no-op default).

    With ``framework`` the livekit-agents tracer exports through the same provider, without
    conversation content.
    """
    global _provider
    _provider = provider
    if provider is not None and framework:
        from livekit.agents.telemetry import set_tracer_provider

        set_tracer_provider(provider, allow_pii=False)


def configure_tracing(exporter: ExporterKind, *, worker_id: str | None = None) -> bool:
    """Process start-up hook: build and install the provider. Returns True when tracing is on."""
    attrs = {"service.instance.id": worker_id} if worker_id else None
    provider = build_provider(exporter, resource_attrs=attrs)
    if provider is None:
        return False
    install(provider)
    trace.set_tracer_provider(provider)
    return True


def flush(timeout_ms: int = 5000) -> None:
    """Export buffered spans (end of a job: the job process may exit right after)."""
    provider = _provider
    if isinstance(provider, TracerProvider):
        provider.force_flush(timeout_ms)


def tracer() -> trace.Tracer:
    provider = _provider
    if provider is None:
        return trace.get_tracer(TRACER_NAME)
    return provider.get_tracer(TRACER_NAME)


def enabled() -> bool:
    return _provider is not None


# --------------------------------------------------------------------------------------------
# Call scope and helpers


def current_call_id() -> str | None:
    return _call_id.get()


@contextmanager
def call_scope(call_id: str | None) -> Iterator[None]:
    """Tasks created inside inherit the call id (asyncio copies the context)."""
    token = _call_id.set(call_id)
    try:
        yield
    finally:
        _call_id.reset(token)


def set_call_id(call_id: str, span: trace.Span | None = None) -> None:
    """Bind the call id once it is known (after the claim) to the context and ``span``."""
    _call_id.set(call_id)
    if span is not None:
        span.set_attribute(CALL_ID_ATTR, call_id)


def _attrs(attributes: Mapping[str, Any] | None) -> dict[str, Any]:
    out = {k: v for k, v in (attributes or {}).items() if v is not None}
    call_id = _call_id.get()
    if call_id and CALL_ID_ATTR not in out:
        out[CALL_ID_ATTR] = call_id
    return out


@contextmanager
def span(name: str, attributes: Mapping[str, Any] | None = None) -> Iterator[trace.Span]:
    """Current span for a block; exceptions are recorded and set the error status."""
    with tracer().start_as_current_span(name, attributes=_attrs(attributes)) as current:
        yield current


def start_span(name: str, attributes: Mapping[str, Any] | None = None) -> trace.Span:
    """A long-lived span (ended by the caller), child of the current span."""
    return tracer().start_span(name, attributes=_attrs(attributes))


def use_span(current: trace.Span) -> Any:
    """Make ``current`` the parent for spans started in the block (does not end it)."""
    return trace.use_span(current, end_on_exit=False)


def _ns(seconds: float) -> int:
    return int(seconds * 1_000_000_000)


def record_turn(record: TurnRecord, *, now: float | None = None) -> None:
    """Emit ``turn`` and its stage spans for a finished turn (no-op when tracing is off).

    Times are wall-clock seconds (``time.time()`` scale, as the session events carry).
    """
    if _provider is None:
        return
    end = record.agent_first_audio_at or (now if now is not None else time.time())
    start = record.user_end_of_speech_at if record.user_end_of_speech_at is not None else end
    start = min(start, end)
    attrs = {
        "turn.index": record.turn_index,
        "turn.e2e_ms": record.e2e_ms,
        "turn.stt_final_ms": record.stt_final_ms,
        "turn.eou_delay_ms": record.eou_delay_ms,
        "turn.llm_ttft_ms": record.llm_ttft_ms,
        "turn.tts_ttfb_ms": record.tts_ttfb_ms,
        "turn.tool_ms": record.tool_ms,
        "turn.interrupted": record.interrupted,
        "turn.greeting": record.turn_index == 0,
    }
    t = tracer()
    turn_span = t.start_span("turn", attributes=_attrs(attrs), start_time=_ns(start))
    ctx = trace.set_span_in_context(turn_span)

    def stage(name: str, begin: float, ms: int | None) -> float:
        if ms is None:
            return begin
        finish = begin + ms / 1000.0
        child = t.start_span(
            name,
            context=ctx,
            attributes=_attrs({"duration_ms": ms}),
            start_time=_ns(begin),
        )
        child.end(end_time=_ns(finish))
        return finish

    if record.turn_index > 0:
        stage("turn.stt", start, record.stt_final_ms)
        decided = stage("turn.eou", start, record.eou_delay_ms)
    else:
        decided = start
    first_token = stage("turn.llm", decided, record.llm_ttft_ms)
    stage("turn.tts", first_token, record.tts_ttfb_ms)
    turn_span.end(end_time=_ns(max(end, start)))


def record_tool_call(
    name: str,
    *,
    ref: str | None = None,
    is_error: bool | None = None,
    duration_ms: int | None = None,
) -> None:
    """A ``tool_call`` span ending now, backdated by ``duration_ms`` when known."""
    if _provider is None:
        return
    end = time.time()
    begin = end - (duration_ms or 0) / 1000.0
    current = tracer().start_span(
        "tool_call",
        attributes=_attrs(
            {
                "tool.name": name,
                "tool.ref": ref,
                "tool.is_error": is_error,
                "tool.duration_ms": duration_ms,
            }
        ),
        start_time=_ns(begin),
    )
    if is_error:
        current.set_status(trace.Status(trace.StatusCode.ERROR, "tool reported an error"))
    current.end(end_time=_ns(end))
