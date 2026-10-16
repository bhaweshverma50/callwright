"""Row-level security for every 003 table (003 T107, Principle V) and workspace derivation on the
internal endpoints (the workspace comes from the call row, never from the request)."""

from __future__ import annotations

import httpx
import pytest
import sqlalchemy.exc
from fastapi import FastAPI
from sqlalchemy import text

from app.calls import pipeline
from app.webhooks_out import service as webhooks
from tests.conftest import Account, signup
from tests.runtime_support import SERVICE_HEADERS, Events, Runtime, agent_config, ended_call, owner_sql

TABLES = (
    "calls",
    "call_events",
    "call_pipeline_steps",
    "webhook_deliveries",
    "webhook_signing_secrets",
    "idempotency_keys",
)


async def _count(runtime: Runtime, table: str, workspace_id: str | None, call_ws: str) -> int:
    async with runtime.db.transaction(workspace_id=workspace_id) as session:
        return int(
            (
                await session.execute(
                    text(f"select count(*) from {table} where workspace_id = :ws"),
                    {"ws": call_ws},
                )
            ).scalar_one()
        )


async def test_tables_are_isolated_per_workspace(app: FastAPI, runtime: Runtime) -> None:
    setup = await ended_call(
        runtime, config=agent_config(advanced={"webhook_url": "https://hooks.example.com/a"})
    )
    ws_a = setup.workspace_id
    await pipeline.run(runtime.db, ws_a, setup.call_id, catalog=runtime.catalog)
    async with runtime.db.transaction(workspace_id=ws_a) as session:
        await webhooks.masked_secret(session, webhooks.key_wrapper(app.state.settings), ws_a)
        await session.execute(
            text(
                "insert into idempotency_keys (workspace_id, endpoint, key, request_hash) "
                "values (:ws, 'e', 'k', 'h')"
            ),
            {"ws": ws_a},
        )
    _, ws_b = await runtime.workspace()
    for table in TABLES:
        assert await _count(runtime, table, ws_a, ws_a) >= 1, table
        assert await _count(runtime, table, ws_b, ws_a) == 0, table
        assert await _count(runtime, table, None, ws_a) == 0, table


async def test_writes_into_another_workspace_are_refused(runtime: Runtime) -> None:
    setup = await ended_call(runtime)
    _, ws_b = await runtime.workspace()
    with pytest.raises(sqlalchemy.exc.DBAPIError):
        async with runtime.db.transaction(workspace_id=ws_b) as session:
            await session.execute(
                text(
                    "insert into call_events (workspace_id, call_id, seq, type, occurred_at) "
                    "values (:ws, :call, 999, 'warning', now())"
                ),
                {"ws": setup.workspace_id, "call": setup.call_id},
            )
    async with runtime.db.transaction(workspace_id=ws_b) as session:
        updated = await session.execute(
            text("update calls set status = 'completed' where id = :id"), {"id": setup.call_id}
        )
        assert updated.rowcount == 0  # type: ignore[attr-defined]


async def test_internal_events_take_the_workspace_from_the_call(
    client: httpx.AsyncClient, runtime: Runtime
) -> None:
    setup = await ended_call(runtime)
    ev = Events()
    ev.seq = 500
    batch = [ev.status("in_progress"), {**ev.turn(1), "workspace_id": "ws_01ARZ3NDEKTSV4RRFFQ69G5FAV"}]
    response = await client.post(
        f"/v1/internal/calls/{setup.call_id}/events", json={"events": batch}, headers=SERVICE_HEADERS
    )
    assert response.status_code == 200
    rows = owner_sql("select distinct workspace_id from call_events where call_id = %s", (setup.call_id,))
    assert rows == [(setup.workspace_id,)]


async def test_deliveries_api_shows_only_own_workspace(
    app: FastAPI, client: httpx.AsyncClient, account: Account, runtime: Runtime
) -> None:
    setup = await ended_call(
        runtime,
        account.workspace_id,
        config=agent_config(advanced={"webhook_url": "https://hooks.example.com/a"}),
    )
    other = await signup(client, app)
    mine = (await client.get("/v1/webhooks/deliveries", headers=account.headers)).json()
    theirs = (
        await client.get(f"/v1/webhooks/deliveries?call_id={setup.call_id}", headers=other.headers)
    ).json()
    assert mine["total"] >= 1 and theirs["total"] == 0
    delivery_id = mine["items"][0]["id"]
    assert (
        await client.get(f"/v1/webhooks/deliveries/{delivery_id}", headers=other.headers)
    ).status_code == 404
    assert (
        await client.post(f"/v1/webhooks/deliveries/{delivery_id}/redeliver", headers=other.headers)
    ).status_code == 404
