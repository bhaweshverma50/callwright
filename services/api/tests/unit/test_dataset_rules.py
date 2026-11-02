"""Dataset add rules (008 T075; data-model dataset_items, FR-025, FR-026)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from app.calls.models import Call
from app.core.errors import ProblemError
from app.datasets.service import MAX_ITEMS, check_capacity, classify

AGENT = "agt_A"


def call(call_id: str, **kw: Any) -> Call:
    values: dict[str, Any] = {
        "id": call_id,
        "agent_id": AGENT,
        "origin": "live",
        "status": "completed",
        "transcript": {"items": [{"type": "message", "role": "user", "text": "Hi"}]},
        "created_at": datetime.now(UTC),
    }
    values.update(kw)
    return Call(**values)


def test_reasons_are_checked_in_order() -> None:
    calls = {
        "c_other": call("c_other", agent_id="agt_B", origin="simulation"),
        "c_sim": call("c_sim", origin="simulation", status="processing"),
        "c_open": call("c_open", status="ended", transcript=None),
        "c_purged": call("c_purged", transcript=None),
        "c_empty": call("c_empty", transcript={"items": [{"type": "message", "role": "user", "text": "  "}]}),
        "c_ok": call("c_ok"),
    }
    ids = ["c_missing", "c_other", "c_sim", "c_open", "c_purged", "c_empty", "c_ok"]
    added, duplicates, invalid = classify(ids, calls, AGENT, set())
    assert added == ["c_ok"] and duplicates == 0
    assert [(i["call_id"], i["reason"]) for i in invalid] == [
        ("c_missing", "not_found"),
        ("c_other", "wrong_agent"),
        ("c_sim", "simulated_call"),
        ("c_open", "not_completed"),
        ("c_purged", "unavailable"),
        ("c_empty", "unavailable"),
    ]


def test_already_present_and_repeated_ids_are_duplicates() -> None:
    calls = {c: call(c) for c in ("c1", "c2", "c3")}
    added, duplicates, invalid = classify(["c1", "c2", "c2", "c3"], calls, AGENT, {"c1"})
    assert added == ["c2", "c3"] and duplicates == 2 and invalid == []


def test_the_spec_example_five_ids() -> None:
    calls = {c: call(c) for c in ("c1", "c2", "c3", "c4")}
    calls["c5"] = call("c5", agent_id="agt_B")
    added, duplicates, invalid = classify(["c1", "c2", "c3", "c4", "c5"], calls, AGENT, {"c1"})
    assert (len(added), duplicates, len(invalid)) == (3, 1, 1)
    assert invalid[0]["reason"] == "wrong_agent"


def test_capacity_is_one_thousand() -> None:
    check_capacity(MAX_ITEMS - 1, 1)
    check_capacity(MAX_ITEMS, 0)
    with pytest.raises(ProblemError) as full:
        check_capacity(MAX_ITEMS - 1, 2)
    assert full.value.status == 422 and full.value.code == "dataset_full"
