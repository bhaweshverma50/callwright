"""OpenTelemetry spans (T106) with an in-memory exporter: call, claim, events, turns, tools."""

from __future__ import annotations

import json
from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
import respx
from callwright_contract.protocol import ClaimRequest
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from tests.harness.runner import HarnessCall
from tests.harness.script_schema import Script
from tests.unit.conftest import make_runtime
from worker import entry, telemetry
from worker.control import RuntimeCallControl
from worker.internal_api import CallClosed, InternalApiClient
from worker.metrics import EventRecorder, TurnRecord
from worker.settings import WorkerSettings
from worker.tools import ToolActivity

BASE = "http://api.test/v1/internal"
CALL_ID = "call_01TELEMETRY0000000000000000"


@pytest.fixture
def spans() -> Iterator[InMemorySpanExporter]:
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(telemetry.CallIdSpanProcessor())
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    telemetry.install(provider, framework=False)
    yield exporter
    telemetry.install(None)


def by_name(exporter: InMemorySpanExporter, name: str) -> list[ReadableSpan]:
    return [s for s in exporter.get_finished_spans() if s.name == name]


async def no_sleep(_: float) -> None:
    return None


def test_noop_by_default() -> None:
    telemetry.install(None)
    assert not telemetry.enabled()
    assert telemetry.build_provider("none") is None
    # Helpers are safe without a provider.
    telemetry.record_turn(TurnRecord(turn_index=1, e2e_ms=500))
    telemetry.record_tool_call("lookup")
    with telemetry.span("x") as span:
        assert not span.is_recording()


def test_settings_select_exporter(monkeypatch: pytest.MonkeyPatch) -> None:
    assert WorkerSettings().otel_exporter == "none"
    monkeypatch.setenv("CALLWRIGHT_OTEL_EXPORTER", "otlp")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://collector.test:4318")
    settings = WorkerSettings()
    assert settings.otel_exporter == "otlp"
    provider = telemetry.build_provider(settings.otel_exporter)
    assert isinstance(provider, TracerProvider)
    assert provider.resource.attributes["service.name"] == "callwright-voice-worker"
    provider.shutdown()
    with pytest.raises(ValueError):
        telemetry.build_provider("zipkin")  # type: ignore[arg-type]


def test_turn_span_has_latency_attributes_and_stages(spans: InMemorySpanExporter) -> None:
    record = TurnRecord(
        turn_index=2,
        user_end_of_speech_at=1000.0,
        agent_first_audio_at=1000.7,
        stt_final_ms=160,
        eou_delay_ms=400,
        llm_ttft_ms=200,
        tts_ttfb_ms=100,
        e2e_ms=700,
    )
    with telemetry.call_scope(CALL_ID):
        EventRecorder().turn(record)
    (turn,) = by_name(spans, "turn")
    attrs = dict(turn.attributes or {})
    assert attrs["call_id"] == CALL_ID
    assert attrs["turn.index"] == 2 and attrs["turn.e2e_ms"] == 700
    assert attrs["turn.llm_ttft_ms"] == 200 and attrs["turn.interrupted"] is False
    assert turn.start_time == 1_000_000_000_000 and turn.end_time == 1_000_700_000_000
    stages = {s.name: s for s in spans.get_finished_spans() if s.name.startswith("turn.")}
    assert set(stages) == {"turn.stt", "turn.eou", "turn.llm", "turn.tts"}
    for stage in stages.values():
        assert stage.parent is not None and stage.parent.span_id == turn.context.span_id
        assert (stage.attributes or {})["call_id"] == CALL_ID
    # LLM starts at the end-of-turn decision, TTS at the first token.
    assert stages["turn.llm"].start_time == stages["turn.eou"].end_time
    assert stages["turn.tts"].start_time == stages["turn.llm"].end_time


def test_greeting_turn_has_no_stt_stage(spans: InMemorySpanExporter) -> None:
    telemetry.record_turn(
        TurnRecord(turn_index=0, user_end_of_speech_at=5.0, agent_first_audio_at=5.9, e2e_ms=900)
    )
    names = {s.name for s in spans.get_finished_spans()}
    assert "turn" in names and "turn.stt" not in names and "turn.eou" not in names


def test_tool_call_span(spans: InMemorySpanExporter) -> None:
    class Backend:
        async def speak(self, text: str, allow_interruptions: bool) -> None: ...
        async def end(self, reason: str, diagnostic: str | None) -> None: ...
        async def send_dtmf(self, digits: str) -> None: ...

    control = RuntimeCallControl(CALL_ID, EventRecorder(), Backend())
    with telemetry.call_scope(CALL_ID):
        control.report_tool(
            ToolActivity("lookup_order", ref="tool_1", output="err", is_error=True, duration_ms=250)
        )
    (span,) = by_name(spans, "tool_call")
    attrs = dict(span.attributes or {})
    assert attrs["tool.name"] == "lookup_order" and attrs["tool.is_error"] is True
    assert attrs["call_id"] == CALL_ID
    assert span.end_time is not None and span.start_time is not None
    assert span.end_time - span.start_time == pytest.approx(250_000_000, rel=0.01)
    assert span.status.status_code.name == "ERROR"


@respx.mock
async def test_internal_api_spans(spans: InMemorySpanExporter) -> None:
    respx.post(f"{BASE}/calls/claim").mock(
        side_effect=[
            httpx.Response(503),
            httpx.Response(200, json={"admitted": False, "call_id": CALL_ID}),
        ]
    )
    respx.post(f"{BASE}/calls/{CALL_ID}/events").mock(
        return_value=httpx.Response(
            200, json={"accepted": 2, "duplicates": 0, "control": {"action": "end_call"}}
        )
    )
    client = InternalApiClient(BASE, "tok", sleep=no_sleep)
    request = ClaimRequest(job_id="j1", room_name="r", worker_id="w", dispatch_metadata={})
    await client.claim(request)
    await client.post_events(CALL_ID, [{"seq": 3}, {"seq": 4}])
    await client.aclose()
    (claim,) = by_name(spans, "internal_api.claim")
    attrs = dict(claim.attributes or {})
    assert attrs["internal_api.attempts"] == 2 and attrs["http.response.status_code"] == 200
    assert attrs["call_id"] == CALL_ID and attrs["claim.admitted"] is False
    (events,) = by_name(spans, "internal_api.events")
    attrs = dict(events.attributes or {})
    assert attrs["events.count"] == 2 and attrs["events.last_seq"] == 4
    assert attrs["control.action"] == "end_call" and attrs["call_id"] == CALL_ID


@respx.mock
async def test_internal_api_error_marks_span(spans: InMemorySpanExporter) -> None:
    respx.post(f"{BASE}/calls/{CALL_ID}/events").mock(return_value=httpx.Response(409))
    client = InternalApiClient(BASE, "tok", sleep=no_sleep)
    with pytest.raises(CallClosed):
        await client.post_events(CALL_ID, [])
    (events,) = by_name(spans, "internal_api.events")
    assert events.status.status_code.name == "ERROR"


class RefusingCtx:
    def __init__(self) -> None:
        self.job = SimpleNamespace(id="job_1", metadata=json.dumps({"call_id": CALL_ID}))
        self.room = SimpleNamespace(name="call-room")
        self.worker_id = "w1"
        self.shutdowns: list[str] = []

    async def connect(self) -> None:
        return None

    async def delete_room(self) -> None:
        return None

    def shutdown(self, reason: str = "") -> None:
        self.shutdowns.append(reason)


@respx.mock
async def test_job_entry_call_root_span(
    spans: InMemorySpanExporter, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = WorkerSettings(CALLWRIGHT_INTERNAL_API_URL=BASE)
    monkeypatch.setattr(entry, "get_settings", lambda: settings)
    respx.post(f"{BASE}/calls/claim").mock(
        return_value=httpx.Response(
            200,
            json={
                "admitted": False,
                "call_id": CALL_ID,
                "refusal": {"disconnect_reason": "concurrency_limit"},
            },
        )
    )
    ctx = RefusingCtx()
    await entry.job_entry(ctx)
    assert ctx.shutdowns == ["refused"]
    (call,) = by_name(spans, "call")
    (claim,) = by_name(spans, "internal_api.claim")
    assert call.parent is None
    assert claim.parent is not None and claim.parent.span_id == call.context.span_id
    attrs = dict(call.attributes or {})
    assert attrs["call_id"] == CALL_ID and attrs["call.admitted"] is False
    assert telemetry.current_call_id() is None  # scope restored after the job


async def test_harness_call_emits_turn_spans(spans: InMemorySpanExporter) -> None:
    """The offline harness drives the same recorder, so turns trace with call_id there too."""
    call: Any = HarnessCall(Script(name="t", steps=[]), dict(make_runtime().config))
    with telemetry.call_scope(CALL_ID):
        await call.connect()
        await call.wait_idle()
    turns = by_name(spans, "turn")
    assert turns and all((t.attributes or {})["call_id"] == CALL_ID for t in turns)
