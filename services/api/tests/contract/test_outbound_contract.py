"""contracts/outbound.yaml, POST /v1/outbound-calls (010 T025)."""

from __future__ import annotations

import httpx

from tests.conftest import Account
from tests.contract.conftest import check
from tests.fakes.livekit_fake import Channels, fresh_e164


async def test_outbound_202_400_401_409_422(
    client: httpx.AsyncClient, account: Account, channels: Channels
) -> None:
    number, agent = await channels.outbound_ready(client, account)
    to = fresh_e164()
    accepted = check(await channels.place(client, account, to_number=to, from_number=number["e164"]))
    assert accepted.status_code == 202, accepted.text
    body = accepted.json()
    assert (
        body["status"] == "queued" and body["agent_id"] == agent and body["phone_number_id"] == number["id"]
    )
    assert body["idempotent_replay"] is False and body["timezone_source"] == "number_region"
    assert body["recipient_timezones"] == ["America/Los_Angeles"]

    missing_key = check(
        await client.post(
            "/v1/outbound-calls",
            json={"to_number": to, "from_number": number["e164"]},
            headers=account.headers,
        )
    )
    assert missing_key.status_code == 400
    unauth = check(
        await client.post(
            "/v1/outbound-calls",
            json={"to_number": to, "from_number": number["e164"]},
            headers={"Idempotency-Key": "abcdefgh1"},
        )
    )
    assert unauth.status_code == 401
    same = check(await channels.place(client, account, to_number=number["e164"], from_number=number["e164"]))
    assert same.status_code == 422 and same.json()["code"] == "same_number"
    bad_tz = check(
        await channels.place(
            client, account, to_number=to, from_number=number["e164"], recipient_timezone="Mars/Base"
        )
    )
    assert bad_tz.status_code == 422 and bad_tz.json()["code"] == "invalid_timezone"
    other = await channels.number(client, account)
    no_agent = check(await channels.place(client, account, to_number=to, from_number=other["e164"]))
    assert no_agent.status_code == 409 and no_agent.json()["code"] == "no_outbound_agent"
