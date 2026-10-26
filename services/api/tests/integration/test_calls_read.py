"""Call history and detail against the seeded workspace (006 T014, US1, US2, US4)."""

from __future__ import annotations

from typing import Any

import httpx

from tests.calls_support import SeededCalls
from tests.runtime_support import owner_sql


async def _get(client: httpx.AsyncClient, seeded: SeededCalls, path: str, **params: Any) -> httpx.Response:
    return await client.get(path, params=params, headers=seeded.a.headers)


async def test_default_order_and_pages(client: httpx.AsyncClient, seeded_calls: SeededCalls) -> None:
    pages = [(await _get(client, seeded_calls, "/v1/calls", page=p)).json() for p in (1, 2, 3)]
    assert [len(p["items"]) for p in pages] == [20, 20, 5]
    assert pages[0]["total"] == 45 and pages[0]["total_pages"] == 3
    started = [i["started_at"] for p in pages for i in p["items"]]
    assert started == sorted(started, reverse=True)
    assert all(i["origin"] in ("live", "test") for p in pages for i in p["items"])
    assert len({i["call_id"] for p in pages for i in p["items"]}) == 45


async def test_origin_filter_shows_simulations(client: httpx.AsyncClient, seeded_calls: SeededCalls) -> None:
    body = (
        await _get(client, seeded_calls, "/v1/calls", origin="live,test,simulation", page_size=100)
    ).json()
    assert body["total"] == 47
    sims = [i for i in body["items"] if i["origin"] == "simulation"]
    assert sorted(i["call_id"] for i in sims) == sorted(seeded_calls.data.simulation_call_ids)


async def test_other_workspace_sees_nothing(client: httpx.AsyncClient, seeded_calls: SeededCalls) -> None:
    b = seeded_calls.b.headers
    listed = await client.get("/v1/calls", params={"origin": "live,test,simulation"}, headers=b)
    assert listed.json()["total"] == 0
    ref = seeded_calls.data.reference_call_id
    for path in ("", "/transcript", "/turn-latencies", "/recording"):
        assert (await client.get(f"/v1/calls/{ref}{path}", headers=b)).status_code == 404
    compare = await client.get(f"/v1/calls/{ref}/compare", params={"with_call_id": ref}, headers=b)
    assert compare.status_code == 404


async def test_filters_combine(client: httpx.AsyncClient, seeded_calls: SeededCalls) -> None:
    body = (
        await _get(client, seeded_calls, "/v1/calls", channel="whatsapp", status="completed", page_size=100)
    ).json()
    assert body["total"] > 0
    assert {i["channel"] for i in body["items"]} == {"whatsapp"}
    assert {i["status"] for i in body["items"]} == {"completed"}
    either = (await _get(client, seeded_calls, "/v1/calls", channel="whatsapp,web", page_size=100)).json()
    whatsapp = (await _get(client, seeded_calls, "/v1/calls", channel="whatsapp", page_size=100)).json()
    web = (await _get(client, seeded_calls, "/v1/calls", channel="web", page_size=100)).json()
    assert either["total"] == whatsapp["total"] + web["total"]


async def test_agent_and_unknown_values(client: httpx.AsyncClient, seeded_calls: SeededCalls) -> None:
    agent = seeded_calls.data.agent_ids[1]
    body = (
        await _get(client, seeded_calls, "/v1/calls", agent_id=agent, status="nonsense", page_size=100)
    ).json()
    assert body["total"] > 0 and {i["agent"]["id"] for i in body["items"]} == {agent}
    assert all(i["agent"]["name"] == "Clinic scheduler" for i in body["items"])


async def test_sort_by_duration_both_ways(client: httpx.AsyncClient, seeded_calls: SeededCalls) -> None:
    asc = (
        await _get(client, seeded_calls, "/v1/calls", sort="duration_s", order="asc", page_size=100)
    ).json()["items"]
    desc = (
        await _get(client, seeded_calls, "/v1/calls", sort="duration_s", order="desc", page_size=100)
    ).json()["items"]
    assert [i["duration_s"] for i in asc] == sorted(i["duration_s"] for i in asc)
    assert [i["duration_s"] for i in desc] == sorted((i["duration_s"] for i in desc), reverse=True)
    costs = [
        i["cost_usd"]
        for i in (await _get(client, seeded_calls, "/v1/calls", sort="cost_usd", page_size=100)).json()[
            "items"
        ]
    ]
    priced = [c for c in costs if c is not None]
    assert priced == sorted(priced, reverse=True) and costs[: len(priced)] == priced


async def test_phone_prefix_and_plus(client: httpx.AsyncClient, seeded_calls: SeededCalls) -> None:
    ref = seeded_calls.data.reference_call_id
    for typed in ("+1555123", "1 (555) 123-45", "15551234567"):
        body = (await _get(client, seeded_calls, "/v1/calls", from_number=typed, page_size=100)).json()
        assert ref in [i["call_id"] for i in body["items"]], typed
    raw = await client.get("/v1/calls?from_number=%2B15551234567", headers=seeded_calls.a.headers)
    assert ref in [i["call_id"] for i in raw.json()["items"]]


async def test_calendar_day_in_timezone(client: httpx.AsyncClient, seeded_calls: SeededCalls) -> None:
    ref = seeded_calls.data.reference_call_id
    owner_sql("update calls set created_at = '2025-02-28T20:00:00Z' where id = %s", (ref,))
    try:
        body = (
            await _get(
                client,
                seeded_calls,
                "/v1/calls",
                start_date="2025-03-01",
                end_date="2025-03-01",
                tz="Asia/Kolkata",
            )
        ).json()
        assert [i["call_id"] for i in body["items"]] == [ref]
        utc = (
            await _get(client, seeded_calls, "/v1/calls", start_date="2025-03-01", end_date="2025-03-01")
        ).json()
        assert utc["total"] == 0
        bad = await _get(client, seeded_calls, "/v1/calls", start_date="2026-10-02", end_date="2026-10-01")
        assert bad.status_code == 422
    finally:
        owner_sql("update calls set created_at = now() where id = %s", (ref,))


async def test_call_id_prefix(client: httpx.AsyncClient, seeded_calls: SeededCalls) -> None:
    ref = seeded_calls.data.reference_call_id
    body = (await _get(client, seeded_calls, "/v1/calls", call_id=ref[:14])).json()
    assert ref in [i["call_id"] for i in body["items"]]
    assert (await _get(client, seeded_calls, "/v1/calls", call_id="call_1")).status_code == 422


async def test_reference_call_detail(client: httpx.AsyncClient, seeded_calls: SeededCalls) -> None:
    ref = seeded_calls.data.reference_call_id
    detail = (await _get(client, seeded_calls, f"/v1/calls/{ref}")).json()
    assert detail["agent_version_label"] == "v1"
    assert detail["processing_state"] == "done"
    header = detail["cost"]["header"]
    assert header["duration_s"] == 271 and round(header["billed_minutes"], 2) == 4.52
    assert round(header["avg_rate_per_min_usd"], 3) == 0.106
    assert [s["multiplier"] for s in detail["cost"]["surcharges"]] == [1.13]
    assert "nc" not in [line["component"] for line in detail["cost"]["lines"]]
    assert detail["latency"]["turns_measured"] >= 1
    assert detail["quality"] == {
        "eval_status": "not_evaluated",
        "pass_count": 0,
        "fail_count": 0,
        "label": None,
    }


async def test_transcript_and_latencies(client: httpx.AsyncClient, seeded_calls: SeededCalls) -> None:
    ref = seeded_calls.data.reference_call_id
    items = (await _get(client, seeded_calls, f"/v1/calls/{ref}/transcript")).json()["items"]
    errors = [i for i in items if i["type"] == "tool_result" and i["is_error"]]
    assert errors and errors[0]["duration_ms"] == 3004
    assert any(i["type"] == "message" and i["interrupted"] for i in items)
    lat = (await _get(client, seeded_calls, f"/v1/calls/{ref}/turn-latencies")).json()
    assert [t["turn_index"] for t in lat["turns"]] == list(range(len(lat["turns"])))
    assert any(t["tts_ttfb_ms"] is None for t in lat["turns"])


async def test_processing_call_hides_analysis(client: httpx.AsyncClient, seeded_calls: SeededCalls) -> None:
    body = (await _get(client, seeded_calls, "/v1/calls", status="processing")).json()
    assert body["total"] == 1
    call = body["items"][0]
    assert call["summary"] is None
    detail = (await _get(client, seeded_calls, f"/v1/calls/{call['call_id']}")).json()
    assert detail["processing_state"] == "pending"
    rec = await _get(client, seeded_calls, f"/v1/calls/{call['call_id']}/recording")
    assert rec.status_code == 409 and rec.json()["code"] == "recording_processing"


async def test_recording_link(client: httpx.AsyncClient, seeded_calls: SeededCalls) -> None:
    with_rec = (await _get(client, seeded_calls, "/v1/calls", page_size=100)).json()["items"]
    call_id = next(i["call_id"] for i in with_rec if i["has_recording"])
    link = await _get(client, seeded_calls, f"/v1/calls/{call_id}/recording", disposition="attachment")
    assert link.status_code == 200 and link.headers["cache-control"] == "no-store"
    assert link.json()["filename"] == f"{call_id}.ogg"
    none = (
        next(i["call_id"] for i in with_rec if not i["has_recording"] and i["status"] == "failed")
        if any(not i["has_recording"] and i["status"] == "failed" for i in with_rec)
        else None
    )
    if none:
        assert (await _get(client, seeded_calls, f"/v1/calls/{none}/recording")).status_code == 404


async def test_compare_two_calls(client: httpx.AsyncClient, seeded_calls: SeededCalls) -> None:
    flow_agent = seeded_calls.data.agent_ids[1]
    calls = (
        await _get(client, seeded_calls, "/v1/calls", agent_id=flow_agent, status="completed", page_size=100)
    ).json()["items"]
    left, right = calls[0]["call_id"], calls[1]["call_id"]
    body = (await _get(client, seeded_calls, f"/v1/calls/{left}/compare", with_call_id=right)).json()
    assert body["right_kind"] == "call"
    assert body["alignment"][0]["turn_index"] == 0
    assert body["flow_diff"] and body["verdict_diffs"] == []
    sim = seeded_calls.data.simulation_call_ids[0]
    srun = f"srun_{sim[5:]}"
    by_run = (
        await _get(client, seeded_calls, f"/v1/calls/{left}/compare", with_simulation_run_id=srun)
    ).json()
    assert by_run["right"]["call_id"] == sim and by_run["right_kind"] == "simulation"
    both = await _get(
        client, seeded_calls, f"/v1/calls/{left}/compare", with_call_id=right, with_simulation_run_id=srun
    )
    neither = await _get(client, seeded_calls, f"/v1/calls/{left}/compare")
    assert both.status_code == 422 and neither.status_code == 422
