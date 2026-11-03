"""Contract tests for the calls read side and recordings (006 T012, T022, T023, T052, T090)."""

from __future__ import annotations

import csv
import io

import httpx

from tests.calls_support import SeededCalls
from tests.contract.conftest import check


async def test_list_calls(client: httpx.AsyncClient, seeded_calls: SeededCalls) -> None:
    h = seeded_calls.a.headers
    check(await client.get("/v1/calls", headers=h))
    check(
        await client.get("/v1/calls", params={"origin": "live,test,simulation", "page_size": 100}, headers=h)
    )
    check(
        await client.get(
            "/v1/calls", params={"sort": "latency_avg_ms", "order": "asc", "status": "failed"}, headers=h
        )
    )
    bad = check(
        await client.get(
            "/v1/calls", params={"start_date": "2026-10-02", "end_date": "2026-10-01"}, headers=h
        )
    )
    assert bad.status_code == 422
    assert check(await client.get("/v1/calls")).status_code == 401


async def test_call_detail_endpoints(client: httpx.AsyncClient, seeded_calls: SeededCalls) -> None:
    h = seeded_calls.a.headers
    ids = [seeded_calls.data.reference_call_id, *seeded_calls.data.call_ids[1:12]]
    for call_id in ids:
        detail = check(await client.get(f"/v1/calls/{call_id}", headers=h))
        assert detail.status_code == 200
        check(await client.get(f"/v1/calls/{call_id}/transcript", headers=h))
        check(await client.get(f"/v1/calls/{call_id}/turn-latencies", headers=h))
    missing = "call_01JZZZZZZZZZZZZZZZZZZZZZZZ"
    assert check(await client.get(f"/v1/calls/{missing}", headers=h)).status_code == 404
    assert check(await client.get(f"/v1/calls/{missing}/transcript", headers=h)).status_code == 404


async def test_compare(client: httpx.AsyncClient, seeded_calls: SeededCalls) -> None:
    h = seeded_calls.a.headers
    left, right = seeded_calls.data.call_ids[1], seeded_calls.data.call_ids[4]
    ok = check(await client.get(f"/v1/calls/{left}/compare", params={"with_call_id": right}, headers=h))
    assert ok.status_code == 200
    sim = seeded_calls.data.simulation_call_ids[0]
    run = check(
        await client.get(
            f"/v1/calls/{left}/compare", params={"with_simulation_run_id": f"srun_{sim[5:]}"}, headers=h
        )
    )
    assert run.json()["right_kind"] == "simulation"
    assert check(await client.get(f"/v1/calls/{left}/compare", headers=h)).status_code == 422
    other = check(
        await client.get(
            f"/v1/calls/{left}/compare", params={"with_call_id": right}, headers=seeded_calls.b.headers
        )
    )
    assert other.status_code == 404 and "Call not found" in other.json()["detail"]


async def test_recording(client: httpx.AsyncClient, seeded_calls: SeededCalls) -> None:
    h = seeded_calls.a.headers
    items = (await client.get("/v1/calls", params={"page_size": 100}, headers=h)).json()["items"]
    recorded = next(i["call_id"] for i in items if i["has_recording"])
    assert check(await client.get(f"/v1/calls/{recorded}/recording", headers=h)).status_code == 200
    unrecorded = next(
        i["call_id"] for i in items if not i["has_recording"] and i["status"] not in ("processing",)
    )
    assert check(await client.get(f"/v1/calls/{unrecorded}/recording", headers=h)).status_code == 404
    processing = next(i["call_id"] for i in items if i["status"] == "processing")
    assert check(await client.get(f"/v1/calls/{processing}/recording", headers=h)).status_code == 409


async def test_export(client: httpx.AsyncClient, seeded_calls: SeededCalls) -> None:
    h = seeded_calls.a.headers
    params = {"channel": "whatsapp", "sort": "duration_s", "order": "asc"}
    listed = (await client.get("/v1/calls", params={**params, "page_size": 100}, headers=h)).json()["items"]
    # openapi-core cannot parse a text/csv body; the CSV shape is asserted below instead.
    response = await client.get(
        "/v1/calls/export", params={**params, "columns": "call_id,status,bogus,duration_s"}, headers=h
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    rows = list(csv.reader(io.StringIO(response.text)))
    assert rows[0] == ["Call ID", "Status", "Duration (s)"]
    assert [r[0] for r in rows[1:]] == [i["call_id"] for i in listed]
    full = await client.get("/v1/calls/export", headers=h)
    assert "transcript" not in full.text.splitlines()[0].lower()


async def test_live_calls(client: httpx.AsyncClient, seeded_calls: SeededCalls) -> None:
    ok = check(await client.get("/v1/calls/live", headers=seeded_calls.a.headers))
    assert ok.status_code == 200 and ok.json()["count"] >= 1
    assert check(await client.get("/v1/calls/live", headers=seeded_calls.b.headers)).json()["count"] == 0
    assert check(await client.get("/v1/calls/live")).status_code == 401
