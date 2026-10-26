"""Row-level security for every 010 table (010 T065, Principle V), and the routing and lookup
functions return routing columns only, never a secret."""

from __future__ import annotations

import httpx
import pytest
import sqlalchemy.exc
from fastapi import FastAPI
from sqlalchemy import text

from tests.conftest import Account, signup
from tests.fakes.livekit_fake import Channels, fresh_e164, whatsapp_body
from tests.runtime_support import owner_sql

TABLES = (
    "phone_numbers",
    "whatsapp_channels",
    "whatsapp_caller_routes",
    "dnc_entries",
    "outbound_calling_hours",
    "outbound_policy_decisions",
)


async def test_tables_are_isolated(
    app: FastAPI, client: httpx.AsyncClient, account: Account, channels: Channels
) -> None:
    number, agent = await channels.outbound_ready(client, account)
    channel = await channels.whatsapp(client, account)
    await client.post(
        f"/v1/whatsapp/channels/{channel['id']}/caller-routes",
        json={"caller_number": "+14085550777", "agent_id": agent},
        headers=account.headers,
    )
    to = fresh_e164()
    await client.post("/v1/dnc-entries", json={"number": to}, headers=account.headers)
    await channels.place(client, account, to_number=to, from_number=number["e164"])
    other = await signup(client, app)
    db = app.state.db
    for table in TABLES:
        assert (
            owner_sql(f"select count(*) from {table} where workspace_id = %s", (account.workspace_id,))[0][0]
            >= 1
        )
        async with db.transaction(workspace_id=other.workspace_id) as session:
            seen = (
                await session.execute(
                    text(f"select count(*) from {table} where workspace_id = :ws"),
                    {"ws": account.workspace_id},
                )
            ).scalar_one()
        assert seen == 0, table
        async with db.transaction() as session:  # no workspace at all
            assert (await session.execute(text(f"select count(*) from {table}"))).scalar_one() == 0, table
    with pytest.raises(sqlalchemy.exc.DBAPIError):
        async with db.transaction(workspace_id=other.workspace_id) as session:
            await session.execute(
                text(
                    "insert into dnc_entries (id, workspace_id, e164, source) values (:id, :ws, :e, 'manual')"
                ),
                {"id": "dnc_01ARZ3NDEKTSV4RRFFQ69G5FAV", "ws": account.workspace_id, "e": fresh_e164()},
            )
    for path in (f"/v1/phone-numbers/{number['id']}", f"/v1/whatsapp/channels/{channel['id']}"):
        assert (await client.get(path, headers=other.headers)).status_code == 404


async def test_routing_functions_return_no_secrets(
    app: FastAPI, client: httpx.AsyncClient, account: Account, channels: Channels
) -> None:
    number = await channels.number(client, account, auth_password="carrier-pass-1")
    body = whatsapp_body()
    channel = await channels.whatsapp(client, account, **body)
    async with app.state.db.transaction() as session:
        rows = [
            (await session.execute(text("select * from route_phone_number(:id)"), {"id": number["id"]}))
            .mappings()
            .one(),
            (
                await session.execute(
                    text("select * from route_whatsapp_channel(:id, :c)"),
                    {"id": channel["id"], "c": "+14085550000"},
                )
            )
            .mappings()
            .one(),
            (
                await session.execute(
                    text("select * from lookup_whatsapp_channel_by_meta_id(:m)"),
                    {"m": body["meta_phone_number_id"]},
                )
            )
            .mappings()
            .one(),
            (await session.execute(text("select * from channels_draining()"))).mappings().first() or {},
        ]
    allowed = {
        "workspace_id",
        "e164",
        "status",
        "inbound_agent_id",
        "inbound_webhook_url",
        "default_agent_id",
        "route_agent_id",
        "channel_id",
        "kind",
        "id",
    }
    for row in rows:
        assert set(row) <= allowed
        text_values = " ".join(str(v) for v in row.values())
        for secret in ("carrier-pass-1", body["access_token"], body["verify_token"], body["app_secret"]):
            assert secret not in text_values
