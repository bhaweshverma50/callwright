"""CallControl: hang-up, keypad tones, tool and flow reporting, segment overrides (FR-046)."""

from __future__ import annotations

import pytest
from callwright_contract.protocol import ControlRange

from tests.unit.conftest import make_runtime
from tests.unit.tool_support import Backend
from worker.adapters.registry import AdapterRegistry
from worker.control import RuntimeCallControl
from worker.metrics import EventRecorder
from worker.pipeline import OverrideManager, clamp_value, plan_session
from worker.tools import CallControl, ToolActivity


def make_control(
    controls: list[ControlRange] | None = None, **config: object
) -> tuple[RuntimeCallControl, Backend, EventRecorder, OverrideManager]:
    registry = AdapterRegistry()
    runtime = make_runtime(dict(config))
    plan = plan_session(runtime, registry)
    recorder = EventRecorder()
    manager = OverrideManager(
        plan,
        registry,
        runtime.controls if controls is None else controls,
        runtime.stt_auto_rules,
        on_system_event=recorder.system,
    )
    backend = Backend()
    return (
        RuntimeCallControl("call_x", recorder, backend, overrides=manager),
        backend,
        recorder,
        manager,
    )


def items(recorder: EventRecorder) -> list[dict[str, object]]:
    return [e["item"] for e in recorder.history if e["type"] == "transcript_item"]


async def test_hang_up_first_writer_wins() -> None:
    control, backend, _, _ = make_control()
    assert isinstance(control, CallControl)
    assert await control.hang_up("max_duration_reached")
    assert not await control.hang_up("inactivity")
    assert backend.ended == ["max_duration_reached"] and backend.diagnostics == [None]
    assert control.disconnect_reason == "max_duration_reached"
    await control.say("too late")
    assert backend.said == []


async def test_send_dtmf_validates_and_reports() -> None:
    control, backend, recorder, _ = make_control()
    await control.send_dtmf("12#")
    assert backend.tones == ["12#"]
    assert recorder.history[-1] == {
        **recorder.history[-1],
        "type": "dtmf",
        "digits": "12#",
        "direction": "sent",
    }
    with pytest.raises(ValueError):
        await control.send_dtmf("12A")


async def test_report_tool_and_transition() -> None:
    control, _, recorder, _ = make_control()
    control.report_tool(
        ToolActivity("lookup", ref="t1", arguments={"id": 1}, output="ok", duration_ms=40)
    )
    control.report_transition("n_2", from_node_id="n_1", label="next")
    types = [e["type"] for e in recorder.history]
    assert types == [
        "tool_call",
        "transcript_item",
        "transcript_item",
        "flow_transition",
        "transcript_item",
    ]
    kinds = [i["type"] for i in items(recorder)]
    assert kinds == ["tool_call", "tool_result", "flow_transition"]


def test_clamp_value_snaps_to_step() -> None:
    table = [ControlRange(path="/tts/speed", min=0.5, max=2.0, step=0.1)]
    assert clamp_value("/tts/speed", 3.0, table) == (2.0, True)
    assert clamp_value("/tts/speed", 0.1, table) == (0.5, True)
    assert clamp_value("/tts/speed", 1.2, table) == (1.2, False)
    assert clamp_value("/tts/speed", 1.23, table) == (1.2, True)
    assert clamp_value("/llm/temperature", 9.0, table) == (9.0, False)


async def test_overrides_clamp_and_apply_at_turn_boundary() -> None:
    control, _, recorder, manager = make_control()
    result = await control.apply_overrides(
        {"tts": {"provider": "cartesia", "model": "sonic-3", "speed": 3.0, "volume": -1}}
    )
    assert result.pending and result.rejected == ()
    assert {c.path for c in result.clamped} == {"tts.speed", "tts.volume"}
    assert [i["event"] for i in items(recorder)] == ["override_clamped", "override_clamped"]
    assert manager.current["tts"].provider == "elevenlabs"  # not before the boundary
    swap = manager.apply_pending()
    assert swap is not None and swap.kinds == ("tts",)
    tts = manager.current["tts"]
    assert (tts.provider, tts.model) == ("cartesia", "sonic-3")
    assert tts.options["speed"] == 2.0 and tts.options["volume"] == 0.0
    assert items(recorder)[-1]["event"] == "segment_override"
    assert manager.apply_pending() is None


async def test_runtime_controls_table_wins() -> None:
    control, _, _, _ = make_control(
        controls=[ControlRange(path="/tts/speed", min=0.8, max=1.2, step=0.1)]
    )
    result = await control.apply_overrides({"tts": {"speed": 1.5}})
    assert result.clamped[0].applied == 1.2


async def test_stt_language_override_re_resolves_auto() -> None:
    control, _, _, manager = make_control()
    assert manager.current["stt"].model == "nova-3"
    await control.apply_overrides({"stt": {"language": "hi"}})
    manager.apply_pending()
    stt = manager.current["stt"]
    assert (stt.model, stt.options["language"]) == ("nova-2", "hi")


async def test_fixed_stt_model_kept_on_language_change() -> None:
    control, _, _, manager = make_control(stt={"provider": "deepgram", "model": "nova-2"})
    await control.apply_overrides({"language": "es"})
    manager.apply_pending()
    assert manager.current["stt"].model == "nova-2"


async def test_unsupported_override_is_rejected_and_previous_kept() -> None:
    control, _, _, manager = make_control()
    result = await control.apply_overrides(
        {"llm": {"provider": "anthropic", "model": "claude"}, "tts": {"speed": 1.1}}
    )
    assert result.rejected == ("llm",)
    assert result.applied_paths == ("tts.speed",)
    swap = manager.apply_pending()
    assert swap is not None and swap.kinds == ("tts",)
    assert manager.current["llm"].provider == "azure_openai"


async def test_auto_stt_for_uncovered_language_is_rejected() -> None:
    control, _, _, _ = make_control(stt={"provider": "assemblyai", "model": None})
    result = await control.apply_overrides({"stt": {"language": "hi"}})
    assert result.rejected == ("stt",)


async def test_control_without_manager_rejects_overrides() -> None:
    control = RuntimeCallControl("call_x", EventRecorder(), Backend())
    result = await control.apply_overrides({"tts": {"speed": 1.0}})
    assert result.rejected == ("tts",) and not result.pending
