"""contracts/outbound.yaml compliance operations (010 T070): do-not-call entries, CSV import,
calling hours, the policy decision log and the ``PolicyBlockedProblem`` body."""

from __future__ import annotations

import httpx

from tests.conftest import Account
from tests.contract.conftest import check
from tests.fakes.livekit_fake import Channels, fresh_e164


async def test_dnc_crud_and_import(client: httpx.AsyncClient, account: Account, channels: Channels) -> None:
    created = check(
        await client.post(
            "/v1/dnc-entries",
            json={"number": "(415) 555-0199", "default_region": "US", "note": "asked"},
            headers=account.headers,
        )
    )
    assert created.status_code == 201
    entry = created.json()
    assert entry["number"] == "+14155550199" and entry["source"] == "manual"
    duplicate = check(
        await client.post("/v1/dnc-entries", json={"number": "+14155550199"}, headers=account.headers)
    )
    assert duplicate.status_code == 409 and duplicate.json()["code"] == "dnc_entry_exists"
    invalid = check(
        await client.post("/v1/dnc-entries", json={"number": "555-0199"}, headers=account.headers)
    )
    assert invalid.status_code == 422 and invalid.json()["code"] == "invalid_number"
    assert check(await client.post("/v1/dnc-entries", json={"number": "+14155550199"})).status_code == 401

    listed = check(await client.get("/v1/dnc-entries?number=415555", headers=account.headers))
    assert listed.status_code == 200 and listed.json()["total"] == 1
    assert check(await client.get("/v1/dnc-entries")).status_code == 401

    csv = b"number,note\n+14155550101,a\n(415) 555-0102,\n+14155550199,dup\nnope,\n+14155550101,again\n"
    imported = check(
        await client.post(
            "/v1/dnc-entries/import",
            files={"file": ("dnc.csv", csv, "text/csv")},
            data={"default_region": "US"},
            headers=account.headers,
        )
    )
    assert imported.status_code == 200
    assert imported.json() == {
        "rows": 5,
        "imported": 2,
        "duplicates": 2,
        "invalid_count": 1,
        "invalid": [{"row": 4, "value": "nope", "error": "This is not a phone number."}],
    }
    bad = check(
        await client.post(
            "/v1/dnc-entries/import",
            files={"file": ("x.csv", b"phone\n1\n", "text/csv")},
            headers=account.headers,
        )
    )
    assert bad.status_code == 422 and bad.json()["code"] == "invalid_csv"

    removed = check(await client.delete(f"/v1/dnc-entries/{entry['id']}", headers=account.headers))
    assert removed.status_code == 204
    again = check(await client.delete(f"/v1/dnc-entries/{entry['id']}", headers=account.headers))
    assert again.status_code == 404


async def test_calling_hours(client: httpx.AsyncClient, account: Account, channels: Channels) -> None:
    default = check(await client.get("/v1/outbound-calling-hours", headers=account.headers))
    assert default.status_code == 200 and default.json()["is_default"] is True
    assert default.json()["windows"]["mon"] == {"start": "09:00", "end": "21:00"}
    days = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
    windows = {d: {"start": "10:00", "end": "18:00"} for d in days} | {"sun": None}
    saved = check(
        await client.put("/v1/outbound-calling-hours", json={"windows": windows}, headers=account.headers)
    )
    assert saved.status_code == 200 and saved.json()["is_default"] is False
    assert saved.json()["windows"]["sun"] is None and saved.json()["updated_by_user_id"] == account.user_id
    broken = {**windows, "mon": {"start": "18:00", "end": "10:00"}}
    invalid = check(
        await client.put("/v1/outbound-calling-hours", json={"windows": broken}, headers=account.headers)
    )
    assert invalid.status_code == 422 and invalid.json()["code"] == "invalid_window"
    assert invalid.json()["errors"][0]["pointer"] == "/windows/mon"
    assert check(await client.get("/v1/outbound-calling-hours")).status_code == 401


async def test_policy_blocks_and_decision_log(
    client: httpx.AsyncClient, account: Account, channels: Channels
) -> None:
    number, _ = await channels.outbound_ready(client, account)
    to = fresh_e164()
    entry = (await client.post("/v1/dnc-entries", json={"number": to}, headers=account.headers)).json()
    blocked = check(await channels.place(client, account, to_number=to, from_number=number["e164"]))
    assert blocked.status_code == 422
    body = blocked.json()
    assert body["type"].endswith("/outbound-policy") and body["reason"] == "dnc_listed"
    assert body["dnc_entry_id"] == entry["id"] and body["to_number"] == to

    await channels.all_day(client, account, None)
    other = fresh_e164()
    hours = check(await channels.place(client, account, to_number=other, from_number=number["e164"]))
    assert hours.status_code == 422 and hours.json()["reason"] == "outside_calling_hours"
    assert hours.json()["recipient_timezones"] == ["America/Los_Angeles"]
    assert hours.json()["timezone_source"] == "number_region" and hours.json()["next_allowed_at"] is None

    log = check(await client.get("/v1/outbound-policy-decisions", headers=account.headers))
    assert log.status_code == 200
    reasons = [d["reason"] for d in log.json()["items"]]
    assert reasons == ["outside_calling_hours", "dnc_listed"]
    assert log.json()["items"][1]["dnc_number"] == to
    filtered = check(
        await client.get(
            f"/v1/outbound-policy-decisions?reason=dnc_listed&to_number=%2B{to[1:]}", headers=account.headers
        )
    )
    assert filtered.json()["total"] == 1
    assert check(await client.get("/v1/outbound-policy-decisions")).status_code == 401
