"""Secrets never leave (010 T038, FR-010, FR-029): no response body and no captured log line
holds a carrier password, WhatsApp access token, verify token, app secret or Meta SIP password,
and the stored values are encrypted."""

from __future__ import annotations

import logging

import httpx
import pytest

from tests.conftest import Account
from tests.fakes.livekit_fake import Channels, whatsapp_body
from tests.runtime_support import owner_sql


async def test_no_secret_in_responses_or_logs(
    client: httpx.AsyncClient, account: Account, channels: Channels, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    password = "carrier-PASS-9f3k2"
    body = whatsapp_body()
    secrets = [password, body["access_token"], body["verify_token"], body["app_secret"]]
    responses: list[httpx.Response] = []
    number = await channels.number(client, account, auth_username="acme", auth_password=password)
    path = f"/v1/phone-numbers/{number['id']}"
    responses.append(await client.get(path, headers=account.headers))
    responses.append(await client.get("/v1/phone-numbers", headers=account.headers))
    responses.append(
        await client.patch(path, json={"auth_password": password + "x"}, headers=account.headers)
    )
    secrets.append(password + "x")
    created = await client.post("/v1/whatsapp/channels", json=body, headers=account.headers)
    responses.append(created)
    channel_path = f"/v1/whatsapp/channels/{created.json()['id']}"
    responses.append(await client.get(channel_path, headers=account.headers))
    responses.append(await client.get("/v1/whatsapp/channels", headers=account.headers))
    responses.append(
        await client.patch(
            channel_path, json={"access_token": "invalid-new-token-abc"}, headers=account.headers
        )
    )
    secrets.append("invalid-new-token-abc")
    logging.getLogger("app.test").warning(
        "payload {'auth_password': '%s', 'access_token': '%s'}", password, body["access_token"]
    )
    sip_password = next(iter(channels.sip.inbound.values())).auth_password if channels.sip.inbound else None
    if sip_password:
        secrets.append(sip_password)
    for response in responses:
        for secret in secrets:
            assert secret not in response.text, (response.request.url, secret)
    from app.core.logging import RedactSecretsFilter

    redactor = RedactSecretsFilter()
    for record in caplog.records:
        redactor.filter(record)
        line = record.getMessage()
        for secret in secrets:
            assert secret not in line, line
    stored = owner_sql(
        "select ciphertext, masked from secrets where workspace_id = %s", (account.workspace_id,)
    )
    assert stored and all(password.encode() not in bytes(c) for c, _ in stored)
    assert all(m.startswith("****") for _, m in stored)
