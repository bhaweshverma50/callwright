"""Contract tests for call labels (007 T044; FR-021, FR-022, US3)."""

from __future__ import annotations

import httpx

from tests.conftest import Account
from tests.contract.conftest import check
from tests.quality_support import seed_agent, seed_call, seed_label, user_id


async def test_label_change_clear_and_filters(client: httpx.AsyncClient, account: Account) -> None:
    h = account.headers
    call = seed_call(account.workspace_id, seed_agent(account.workspace_id))
    url = f"/v1/calls/{call}/annotations"
    empty = check(await client.get(url, headers=h)).json()
    assert empty == {"mine": None, "items": []}
    good = check(await client.put(f"{url}/me", json={"label": "good", "note": "clean booking"}, headers=h))
    assert (
        good.status_code == 200 and good.json()["label"] == "good" and good.json()["note"] == "clean booking"
    )
    listed = await client.get("/v1/calls", params={"label": "good", "call_id": call}, headers=h)
    assert [i["call_id"] for i in listed.json()["items"]] == [call]
    assert listed.json()["items"][0]["quality"]["label"] == "good"
    bad = check(await client.put(f"{url}/me", json={"label": "bad"}, headers=h))
    assert (
        bad.json()["id"] == good.json()["id"] and bad.json()["label"] == "bad" and bad.json()["note"] is None
    )
    assert [
        i["call_id"]
        for i in (await client.get("/v1/calls", params={"label": "bad", "call_id": call}, headers=h)).json()[
            "items"
        ]
    ] == [call]
    assert (await client.get("/v1/calls", params={"label": "good", "call_id": call}, headers=h)).json()[
        "items"
    ] == []
    assert check(await client.delete(f"{url}/me", headers=h)).status_code == 204
    assert check(await client.delete(f"{url}/me", headers=h)).status_code == 204  # idempotent
    unlabelled = (
        await client.get("/v1/calls", params={"label": "unannotated", "call_id": call}, headers=h)
    ).json()
    assert [i["call_id"] for i in unlabelled["items"]] == [call]


async def test_note_limit_and_teammates(client: httpx.AsyncClient, account: Account) -> None:
    h = account.headers
    call = seed_call(account.workspace_id, seed_agent(account.workspace_id))
    url = f"/v1/calls/{call}/annotations"
    long = check(await client.put(f"{url}/me", json={"label": "good", "note": "x" * 2001}, headers=h))
    assert long.status_code == 422 and long.json()["errors"][0]["pointer"] == "/note"
    assert (
        check(
            await client.put(f"{url}/me", json={"label": "good", "note": "x" * 2000}, headers=h)
        ).status_code
        == 200
    )
    seed_label(account.workspace_id, call, user_id(), "bad")
    body = check(await client.get(url, headers=h)).json()
    assert body["mine"]["user"]["id"] == account.user_id and len(body["items"]) == 2
    assert body["items"][0]["id"] == body["mine"]["id"]
    assert check(await client.put(f"{url}/me", json={"label": "meh"}, headers=h)).status_code == 422
    missing = "/v1/calls/call_01ARZ3NDEKTSV4RRFFQ69G5FAV/annotations/me"
    assert check(await client.put(missing, json={"label": "good"}, headers=h)).status_code == 404
