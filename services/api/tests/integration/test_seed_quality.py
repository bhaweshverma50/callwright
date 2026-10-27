"""The 007 quickstart seed (T012) gives the numbers quickstart.md expects (sections 5 and 7)."""

from __future__ import annotations

import httpx
import psycopg
import pytest

from app.dev.seed_quality import seed
from tests.conftest import Account
from tests.contract.conftest import check
from tests.runtime_support import _owner_dsn


async def test_seed_matches_quickstart(client: httpx.AsyncClient, account: Account) -> None:
    with psycopg.connect(_owner_dsn(), autocommit=True) as conn:
        out = seed(conn, account.workspace_id)
    h = account.headers
    rows = check(await client.get("/v1/calibration/evaluators", headers=h)).json()["items"]
    intent = next(r for r in rows if r["evaluator_name"] == "intent_fulfillment")
    assert (intent["both_pass"], intent["both_fail"], intent["over_eager"], intent["missed"]) == (4, 2, 2, 2)
    assert intent["agreement_rate"] == pytest.approx(0.6) and intent["reading"] == "partial"
    assert check(await client.get("/v1/review/queue/summary", headers=h)).json() == {
        "random": 12,
        "failed": 7,
        "disagreement": 4,
    }
    agent = out.agents["booking_desk"]
    variables = check(await client.get(f"/v1/agents/{agent}/analysis-variables", headers=h)).json()["items"]
    assert [v["name"] for v in variables] == ["appointment_booked", "preferred_day"]
    settings = check(await client.get(f"/v1/agents/{agent}/eval-settings", headers=h)).json()["items"]
    intent_setting = next(s for s in settings if s["name"] == "intent_fulfillment")
    assert intent_setting["enabled"] and intent_setting["is_headline"]
