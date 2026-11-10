"""Flow scenarios (004 T050, T076): scripted callers through compiled flows on the real
``AgentSession`` in text mode, asserting node paths, triggers, spoken lines and how the call
ends. Scenarios are tests/harness/scenarios/flow_*.yaml; flows are tests/harness/flows/."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest

from tests.flow_support import SCENARIOS, compiled_config, load_scenario, run_flow_call, script_from

FILES = sorted(SCENARIOS.glob("flow_*.yaml"))


@pytest.fixture
def no_llm_prewarm(monkeypatch: pytest.MonkeyPatch) -> None:
    from livekit.agents import llm

    monkeypatch.setattr(llm.LLM, "prewarm", lambda self, **_: None)


@pytest.mark.usefixtures("no_llm_prewarm")
@pytest.mark.parametrize("path", FILES, ids=[p.stem for p in FILES])
async def test_flow_scenario(path: Path) -> None:
    data = load_scenario(path)
    config: dict[str, Any] = copy.deepcopy(compiled_config(str(data["flow"])))
    runtime = dict(data.get("runtime") or {})
    result = await run_flow_call(config, script_from(data), list(data["caller"]), runtime=runtime)
    expect = data["expect"]
    control = result.control
    if "path" in expect:
        assert control.path == expect["path"]
    if "triggers" in expect:
        assert [t["trigger"] for t in control.transitions] == expect["triggers"]
    if "moves" in expect:
        assert len(control.transitions) == expect["moves"]
    if "end_reason" in expect:
        assert control.disconnect_reason == expect["end_reason"]
    if "diagnostic" in expect:
        assert control.diagnostic == expect["diagnostic"]
    for line in expect.get("agent_says") or []:
        assert line in result.replies
    for name, value in (expect.get("variables") or {}).items():
        moved = [t.get("variables") or {} for t in control.transitions]
        assert any(v.get(name) == value for v in moved)
    for move in control.transitions:
        assert move["engine_ms"] >= 0 and "t_ms" in move and move["to_label"]
    if "reset_hides" in expect:
        # The reset node's model calls never see the earlier turn's details.
        secret = str(expect["reset_hides"])
        spanish = [ctx for ctx, tools in result.llm.requests if "route_to_wrap_up" in tools]
        assert spanish
        for ctx in spanish:
            said = [
                str(getattr(i, "text_content", "") or "")
                for i in ctx.items
                if getattr(i, "role", "") in ("user", "assistant")
            ]
            assert secret not in " ".join(said)
