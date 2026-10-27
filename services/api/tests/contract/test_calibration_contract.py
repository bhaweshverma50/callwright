"""Contract tests for calibration (007 T049)."""

from __future__ import annotations

import httpx

from tests.conftest import Account
from tests.contract.conftest import check


async def test_empty_workspace(client: httpx.AsyncClient, account: Account) -> None:
    h = account.headers
    rows = check(await client.get("/v1/calibration/evaluators", headers=h)).json()
    assert rows == {"min_sample_for_signal": 5, "items": []}
    summary = check(await client.get("/v1/calibration/summary", headers=h)).json()
    assert summary == {
        "annotated_calls": 0,
        "annotated_and_evaluated_calls": 0,
        "conflicting_label_calls": 0,
        "min_sample_for_signal": 5,
    }
    for params in (
        {"version_scope": "all"},
        {"lookback_days": 7},
        {"agent_id": "agt_01ARZ3NDEKTSV4RRFFQ69G5FAV"},
    ):
        assert (
            check(await client.get("/v1/calibration/evaluators", params=params, headers=h)).status_code == 200
        )
