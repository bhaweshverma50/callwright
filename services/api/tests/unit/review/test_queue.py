"""Review queue strategies and counts (007 T063, T064; FR-023 to FR-025, US6)."""

from __future__ import annotations

from datetime import timedelta

import httpx

from tests.conftest import Account
from tests.contract.conftest import check
from tests.quality_support import seed_agent, seed_call, seed_label, seed_run, user_id

CHECKS = ("latency_slo", "audio_silence", "intent_fulfillment", "tool_call_correctness", "kb_relevance")


def seed_queue(ws: str) -> dict[str, list[str]]:
    """12 unlabelled live calls: 4 mixed, 3 all failed, 5 all passed (US6 independent test)."""
    agent = seed_agent(ws)
    out: dict[str, list[str]] = {"mixed": [], "failed": [], "passed": []}
    splits = [(3, 2), (1, 4), (2, 2), (4, 1)]  # mixed: closest split first is (2,2), then (3,2)/(4,1)...
    for i, (passes, fails) in enumerate(splits):
        call = seed_call(ws, agent, ended_ago=timedelta(hours=i + 1))
        for n in range(passes + fails):
            seed_run(ws, call, agent[0], CHECKS[n], "pass" if n < passes else "fail")
        out["mixed"].append(call)
    for i in range(3):
        call = seed_call(ws, agent, ended_ago=timedelta(hours=10 + i))
        for n in range(i + 1):
            seed_run(ws, call, agent[0], CHECKS[n], "fail")
        out["failed"].append(call)
    for i in range(5):
        call = seed_call(ws, agent, ended_ago=timedelta(hours=20 + i))
        seed_run(ws, call, agent[0], CHECKS[0], "pass")
        out["passed"].append(call)
    # Out of scope: simulated, older than the lookback, and a call this user already labelled.
    seed_run(ws, seed_call(ws, agent, origin="simulation"), agent[0], CHECKS[0], "fail")
    seed_call(ws, agent, ended_ago=timedelta(days=40))
    return out


async def test_counts_order_and_labelling(client: httpx.AsyncClient, account: Account) -> None:
    h = account.headers
    seeded = seed_queue(account.workspace_id)
    summary = check(await client.get("/v1/review/queue/summary", headers=h)).json()
    assert summary == {"random": 12, "failed": 7, "disagreement": 4}
    queue = check(await client.get("/v1/review/queue", headers=h)).json()
    assert queue["strategy"] == "disagreement"
    splits = [(i["pass_count"], i["fail_count"]) for i in queue["items"]]
    assert splits == [(2, 2), (3, 2), (1, 4), (4, 1)]
    assert all(i["eval_count"] == i["pass_count"] + i["fail_count"] for i in queue["items"])
    failed = check(await client.get("/v1/review/queue", params={"strategy": "failed"}, headers=h)).json()[
        "items"
    ]
    assert [i["fail_count"] for i in failed] == [4, 3, 2, 2, 2, 1, 1]
    random_a = check(await client.get("/v1/review/queue", params={"strategy": "random"}, headers=h)).json()[
        "items"
    ]
    random_b = check(await client.get("/v1/review/queue", params={"strategy": "random"}, headers=h)).json()[
        "items"
    ]
    assert [i["call_id"] for i in random_a] == [i["call_id"] for i in random_b] and len(random_a) == 12
    # A teammate's label does not hide the call; the viewer's own label does.
    seed_label(account.workspace_id, seeded["mixed"][2], user_id(), "good")
    assert check(await client.get("/v1/review/queue/summary", headers=h)).json()["disagreement"] == 4
    put = await client.put(
        f"/v1/calls/{seeded['mixed'][2]}/annotations/me", json={"label": "good"}, headers=h
    )
    assert put.status_code == 200
    assert check(await client.get("/v1/review/queue/summary", headers=h)).json() == {
        "random": 11,
        "failed": 6,
        "disagreement": 3,
    }
    limited = check(
        await client.get("/v1/review/queue", params={"strategy": "random", "limit": 2}, headers=h)
    )
    assert len(limited.json()["items"]) == 2


async def test_agent_filter_and_empty_state(client: httpx.AsyncClient, account: Account) -> None:
    h = account.headers
    seed_queue(account.workspace_id)
    other = seed_agent(account.workspace_id)
    scoped = check(
        await client.get("/v1/review/queue/summary", params={"agent_id": other[0]}, headers=h)
    ).json()
    assert scoped == {"random": 0, "failed": 0, "disagreement": 0}
    assert (
        check(await client.get("/v1/review/queue", params={"agent_id": "nope"}, headers=h)).status_code == 422
    )
    assert (
        check(await client.get("/v1/review/queue", params={"lookback_days": 91}, headers=h)).status_code
        == 422
    )
