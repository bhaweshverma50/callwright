"""Money test (003 T047, FR-025): the running cost against balance plus grace decides ``end_call``."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi import FastAPI

from app.call_events.service import credit_control, running_cost
from app.calls.models import Call
from app.core.ids import new_id
from tests.runtime_support import Runtime

GRACE = Decimal("0.50")


@pytest.mark.parametrize(
    ("balance", "cost", "action"),
    [
        ("5.00", "1.00", "none"),
        ("0.10", "0.60", "none"),  # 0.10 - 0.60 = -0.50: at the grace, not below it
        ("0.10", "0.600001", "end_call"),
        ("0.00", "0.50", "none"),
        ("0.00", "0.51", "end_call"),
        ("-1.00", "0.00", "end_call"),
    ],
)
def test_threshold(balance: str, cost: str, action: str) -> None:
    control = credit_control(Decimal(balance), Decimal(cost), GRACE)
    assert control.action == action
    assert control.disconnect_reason == ("insufficient_credit" if action == "end_call" else None)


async def test_running_cost_uses_meters_and_connected_time(app: FastAPI, runtime: Runtime) -> None:
    _, ws = await runtime.workspace()
    agent = runtime.versions.add_agent(ws)
    now = datetime.now(UTC)
    call = Call(
        id=new_id("call"),
        workspace_id=ws,
        agent_id=agent.agent_id,
        agent_version_id=agent.draft.version_id,
        channel="web",
        direction="inbound",
        status="in_progress",
        connected_at=now - timedelta(seconds=60),
        usage={
            "llm": [{"provider": "azure_openai", "model": "gpt-5.1", "input_tokens": 0, "output_tokens": 0}]
        },
    )
    async with app.state.db.transaction(workspace_id=ws) as session:
        cost = await running_cost(session, call, runtime.catalog, now)
        # One minute on the default stack, each line rounded up to $0.001:
        # 0.009 (stt) + 0.017 (llm) + 0.045 (tts) + 0 (nc) + 0.05 (platform).
        assert cost == Decimal("0.121")
        call.usage = {
            "llm": [
                {"provider": "azure_openai", "model": "gpt-5.1", "input_tokens": 40000, "output_tokens": 0}
            ]
        }
        # 40,000 input tokens is two minutes of the 20,000/min bundle: the LLM line doubles.
        assert await running_cost(session, call, runtime.catalog, now) == Decimal("0.137")
        call.connected_at = None
        assert await running_cost(session, call, runtime.catalog, now) is None
