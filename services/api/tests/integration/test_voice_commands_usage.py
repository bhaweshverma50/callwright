"""The voice copilot records its model usage as tokens and never bills the workspace."""

from __future__ import annotations

from decimal import Decimal

import httpx

from app.llms.adapters.base import estimate_tokens
from tests.calls_support import SeededCalls
from tests.runtime_support import owner_sql

TRANSCRIPT = "show me failed calls from yesterday"


async def test_interpret_records_tokens_non_billable(
    client: httpx.AsyncClient, seeded_calls: SeededCalls
) -> None:
    ws = seeded_calls.a.workspace_id
    state = {
        "current_route": "/dashboard",
        "page_title": "Dashboard",
        "current_datetime": "2026-10-16T10:00:00Z",
        "timezone": "UTC",
        "available_actions": [],
        "highlightable_elements": [],
    }
    before = len(
        owner_sql(
            "select 1 from usage_events where workspace_id = %s and feature_key = 'voice_copilot'", (ws,)
        )
    )
    r = await client.post(
        "/v1/voice-commands/interpret",
        json={"transcript": TRANSCRIPT, "visual_state": state},
        headers=seeded_calls.a.headers,
    )
    assert r.status_code == 200
    rows = owner_sql(
        "select unit, quantity, billable_cost_usd from usage_events "
        "where workspace_id = %s and feature_key = 'voice_copilot'",
        (ws,),
    )
    assert len(rows) == before + 1
    unit, quantity, billable = rows[-1]
    assert unit == "tokens" and Decimal(quantity) == estimate_tokens(TRANSCRIPT) + 300 + 40
    assert Decimal(billable) == 0
