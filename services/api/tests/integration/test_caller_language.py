"""Caller language (012): the claim offers the languages the agent can switch to, a switch on a
phone call is saved for the caller and the next call (inbound, outbound or callback) starts in
it; browser calls, simulations and agents with switching off never save or use one; the public
endpoints and row-level security."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from fastapi import FastAPI

from app.callbacks.service import place_due
from tests.conftest import Account, signup
from tests.fakes.livekit_fake import Channels, fresh_e164
from tests.integration.test_callbacks import deps
from tests.runtime_support import (
    SERVICE_HEADERS,
    Runtime,
    admitted_call,
    dispatch_metadata,
    owner_sql,
    start_web_call,
)


async def inbound(
    client: httpx.AsyncClient, account: Account, channels: Channels, caller: str, **config: Any
) -> tuple[str, dict[str, Any], dict[str, Any]]:
    """A claimed inbound phone call from ``caller``: (call id, runtime, number)."""
    agent = channels.agent(account.workspace_id, **config)
    number = await channels.number(client, account, inbound_agent_id=agent)
    await channels.all_day(client, account)
    claim = await channels.claim_inbound(
        client, channel="sip_inbound", route_ref=number["id"], trunk_number=number["e164"], caller=caller
    )
    assert claim["admitted"], claim
    return str(claim["call_id"]), claim["runtime"], number


async def report(
    client: httpx.AsyncClient, call_id: str, language: str, offset_ms: int = 42_000
) -> httpx.Response:
    return await client.post(
        f"/v1/internal/calls/{call_id}/language",
        json={"language": language, "offset_ms": offset_ms},
        headers=SERVICE_HEADERS,
    )


async def claim_dispatched(client: httpx.AsyncClient, runtime: Runtime, call_id: str) -> dict[str, Any]:
    response = await client.post(
        "/v1/internal/calls/claim",
        json={
            "job_id": f"AJ_{uuid.uuid4().hex[:10]}",
            "room_name": f"call-{call_id}",
            "worker_id": "AW",
            "dispatch_metadata": dispatch_metadata(runtime, call_id),
        },
        headers=SERVICE_HEADERS,
    )
    assert response.status_code == 200 and response.json()["admitted"], response.text
    body: dict[str, Any] = response.json()["runtime"]
    return body


async def test_switch_is_saved_and_next_inbound_call_starts_in_it(
    client: httpx.AsyncClient, account: Account, channels: Channels
) -> None:
    caller = fresh_e164()
    call_id, runtime, _ = await inbound(client, account, channels, caller)
    options = runtime["language_options"]
    assert options[0]["code"] == "en-US" and options[0]["stt_model"] == "nova-3"
    hindi = next(o for o in options if o["code"] == "hi")
    assert hindi == {"code": "hi", "label": "Hindi", "stt_model": "nova-2", "tts_model": "eleven_flash_v2_5"}
    assert not [o for o in options[1:] if o["code"].startswith("en")]
    assert runtime["caller_language"] is None

    stored = await report(client, call_id, "hi")
    assert stored.status_code == 200, stored.text
    assert stored.json() == {"recorded": True, "stored": True, "reason": "saved"}
    view = (await client.get(f"/v1/calls/{call_id}/language", headers=account.headers)).json()
    assert view["started_from"] == "agent" and view["agent_language"] == {
        "code": "en-US",
        "label": "English (US)",
    }
    assert view["switches"] == [
        {
            "offset_ms": 42_000,
            "from": {"code": "en-US", "label": "English (US)"},
            "to": {"code": "hi", "label": "Hindi"},
        }
    ]
    assert view["caller_number"] == caller and view["preference"]["language"]["code"] == "hi"
    assert view["preference"]["last_call_id"] == call_id

    second, runtime2, _ = await inbound(client, account, channels, caller)
    assert runtime2["caller_language"] == "hi"
    again = await claim_again(client, channels, second, runtime2)
    assert again == "hi"  # a retried claim gives the same answer and records one start
    view2 = (await client.get(f"/v1/calls/{second}/language", headers=account.headers)).json()
    assert view2["started_from"] == "saved_preference" and view2["started_language"]["code"] == "hi"
    assert owner_sql(
        "select count(*) from call_languages where call_id = %s and kind = 'start'", (second,)
    ) == [(1,)]

    # Switching back saves English again; the view shows the switch from Hindi.
    assert (await report(client, second, "en-US", 5_000)).json()["stored"]
    view3 = (await client.get(f"/v1/calls/{second}/language", headers=account.headers)).json()
    assert [(s["from"]["code"], s["to"]["code"]) for s in view3["switches"]] == [("hi", "en-US")]
    third, runtime3, _ = await inbound(client, account, channels, caller)
    assert runtime3["caller_language"] is None  # the agent's own language needs nothing special
    assert third


async def claim_again(
    client: httpx.AsyncClient, channels: Channels, call_id: str, runtime: dict[str, Any]
) -> Any:
    rows = owner_sql("select worker_job_id, room_name from calls where id = %s", (call_id,))
    job_id, room = rows[0]
    response = await client.post(
        "/v1/internal/calls/claim",
        json={
            "job_id": job_id,
            "room_name": room,
            "worker_id": "AW",
            "dispatch_metadata": {"call_id": call_id},
        },
        headers=SERVICE_HEADERS,
    )
    assert response.status_code == 200, response.text
    return response.json()["runtime"]["caller_language"]


async def test_outbound_calls_and_callbacks_start_in_the_saved_language(
    app: FastAPI, client: httpx.AsyncClient, account: Account, channels: Channels
) -> None:
    caller = fresh_e164()
    call_id, _, number = await inbound(client, account, channels, caller)
    assert (await report(client, call_id, "es")).json()["stored"]

    booked = await client.post(
        f"/v1/internal/calls/{call_id}/callbacks",
        json={"in_minutes": 30, "note": "Finish"},
        headers=SERVICE_HEADERS,
    )
    assert booked.status_code == 201, booked.text
    listed = (await client.get(f"/v1/callbacks?source_call_id={call_id}", headers=account.headers)).json()
    at = datetime.fromisoformat(listed["items"][0]["scheduled_at"].replace("Z", "+00:00"))
    assert await place_due(deps(app), now=at + timedelta(seconds=5)) == 1
    placed = (await client.get(f"/v1/callbacks/{listed['items'][0]['id']}", headers=account.headers)).json()
    runtime = await claim_dispatched(client, channels.runtime, placed["call_id"])
    assert runtime["outbound_dial"]["to_number"] == caller and runtime["caller_language"] == "es"

    # A plain outbound call to the same person too; another number gets the agent's language.
    agent = channels.agent(account.workspace_id)
    out_number = await channels.number(client, account, outbound_agent_id=agent)
    for to, expected in ((caller, "es"), (fresh_e164(), None)):
        placed_call = await channels.place(client, account, to_number=to, from_number=out_number["e164"])
        assert placed_call.status_code == 202, placed_call.text
        rt = await claim_dispatched(client, channels.runtime, placed_call.json()["call_id"])
        assert rt["caller_language"] == expected
    assert number


async def test_browser_calls_and_simulations_never_save(
    client: httpx.AsyncClient, account: Account, runtime: Runtime
) -> None:
    agent = runtime.versions.add_agent(account.workspace_id)
    session = await start_web_call(client, account.headers, agent.agent_id)
    assert session.status_code == 201, session.text
    call_id = session.json()["call_id"]
    rt = await claim_dispatched(client, runtime, call_id)
    assert len(rt["language_options"]) > 1 and rt["caller_language"] is None
    out = await report(client, call_id, "fr")
    assert out.json() == {"recorded": True, "stored": False, "reason": "not_phone_call"}
    view = (await client.get(f"/v1/calls/{call_id}/language", headers=account.headers)).json()
    assert view["caller_number"] is None and view["preference"] is None
    assert [s["to"]["code"] for s in view["switches"]] == ["fr"]

    sim = await admitted_call(runtime, account.workspace_id, origin="simulation")
    out = await report(client, sim.call_id, "fr")
    assert out.json()["stored"] is False and out.json()["reason"] in ("simulation", "not_phone_call")
    assert owner_sql(
        "select count(*) from caller_preferences where workspace_id = %s", (account.workspace_id,)
    ) == [(0,)]

    bad = await report(client, call_id, "xx-YY")
    assert bad.status_code == 422
    unauth = await client.post(f"/v1/internal/calls/{call_id}/language", json={"language": "fr"})
    assert unauth.status_code == 401


async def test_switching_off_gives_no_options(
    client: httpx.AsyncClient, account: Account, channels: Channels
) -> None:
    caller = fresh_e164()
    call_id, _, _ = await inbound(client, account, channels, caller)
    assert (await report(client, call_id, "hi")).json()["stored"]
    off = {
        "webhook_url": None,
        "webhook_timeout_ms": 3000,
        "language_switching": {"enabled": False, "languages": []},
    }
    _, runtime, _ = await inbound(client, account, channels, caller, advanced=off)
    assert runtime["language_options"] == [] and runtime["caller_language"] is None

    only = {
        "webhook_url": None,
        "webhook_timeout_ms": 3000,
        "language_switching": {"enabled": True, "languages": ["fr"]},
    }
    _, runtime, _ = await inbound(client, account, channels, caller, advanced=only)
    assert [o["code"] for o in runtime["language_options"]] == ["en-US", "fr"]
    assert runtime["caller_language"] is None  # Hindi is not offered by this agent


async def test_public_endpoints_and_isolation(
    app: FastAPI, client: httpx.AsyncClient, account: Account, channels: Channels
) -> None:
    caller = fresh_e164()
    call_id, _, _ = await inbound(client, account, channels, caller)
    await report(client, call_id, "de")
    listed = await client.get(
        f"/v1/caller-preferences?phone_number={caller.replace('+', '%2B')}", headers=account.headers
    )
    assert listed.status_code == 200 and listed.json()["total"] == 1
    pref = listed.json()["items"][0]
    assert pref["id"].startswith("cpf_") and pref["language"] == {"code": "de", "label": "German"}
    assert datetime.fromisoformat(pref["updated_at"]) <= datetime.now(UTC)

    other = await signup(client, app)
    assert (await client.get("/v1/caller-preferences", headers=other.headers)).json()["total"] == 0
    assert (
        await client.delete(f"/v1/caller-preferences/{pref['id']}", headers=other.headers)
    ).status_code == 404
    assert (await client.get(f"/v1/calls/{call_id}/language", headers=other.headers)).status_code == 404
    rls = owner_sql(
        "select relrowsecurity, relforcerowsecurity from pg_class "
        "where relname in ('caller_preferences', 'call_languages')"
    )
    assert rls == [(True, True), (True, True)]

    assert (
        await client.delete(f"/v1/caller-preferences/{pref['id']}", headers=account.headers)
    ).status_code == 204
    assert (await client.get("/v1/caller-preferences", headers=account.headers)).json()["total"] == 0
    view = (await client.get(f"/v1/calls/{call_id}/language", headers=account.headers)).json()
    assert view["preference"] is None and view["switches"]
    assert (
        await client.delete(f"/v1/caller-preferences/{pref['id']}", headers=account.headers)
    ).status_code == 404
