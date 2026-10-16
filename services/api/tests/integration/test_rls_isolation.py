"""Tenant isolation at the database layer (T024, T045, T060, T074, T082, Principle V).

Workspace B's RLS context cannot read workspace A's rows in any tenant table, even by id, and
cannot write rows into A. Later features add their tables to ``TENANT_TABLES`` (002 T044: agents,
agent_versions, ambient_audio_files).
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.billing import service
from app.core.ids import new_id
from app.core.secrets import LocalKeyWrapper, put_secret
from app.pricing import engine
from tests.conftest import Account, signup
from tests.integration.billing.stripe_fixtures import start_checkout

# table -> column holding the tenant key
TENANT_TABLES = {
    "workspaces": "id",
    "credit_transactions": "workspace_id",
    "checkout_sessions": "workspace_id",
    "call_costs": "workspace_id",
    "usage_events": "workspace_id",
    "secrets": "workspace_id",
    "agents": "workspace_id",
    "agent_versions": "workspace_id",
    "ambient_audio_files": "workspace_id",
}


@pytest.fixture
async def populated(client: httpx.AsyncClient, app: FastAPI) -> tuple[Account, Account]:
    a = await signup(client, app)
    b = await signup(client, app)
    await start_checkout(client, a)
    async with app.state.db.transaction(workspace_id=a.workspace_id) as session:
        await service.charge_call(
            session,
            service.CallUsage(
                workspace_id=a.workspace_id,
                call_id=new_id("call"),
                agent_version_id=None,
                started_at=datetime.now(UTC),
                duration_ms=60_000,
                components=engine.Components(
                    engine.Selection("deepgram"),
                    engine.Selection("openai", "gpt-5-mini"),
                    engine.Selection("cartesia", "sonic-3"),
                ),
                meters={},
            ),
        )
        await service.charge_feature(
            session,
            workspace_id=a.workspace_id,
            feature_key="analytics_chat",
            quantity=Decimal(1),
            unit="requests",
            raw_cost_usd=Decimal("0.001"),
            billable_cost_usd=Decimal("0.002"),
            idempotency_key="rls",
        )
        await put_secret(
            session,
            LocalKeyWrapper(app.state.settings.secrets_master_key.get_secret_value()),
            a.workspace_id,
            "sip_password",
            "hunter2-secret",
        )
    created = await client.post(
        "/v1/agents",
        json={"name": "Tenant A agent", "type": "single_prompt", "config": {"prompt": "x"}},
        headers=a.headers,
    )
    assert created.status_code == 201, created.text
    upload = await client.post(
        "/v1/voices/ambient-audio",
        files={"file": ("a.mp3", b"ID3" + b"\x00" * 32, "audio/mpeg")},
        headers=a.headers,
    )
    assert upload.status_code == 201, upload.text
    return a, b


@pytest.mark.parametrize(("table", "column"), sorted(TENANT_TABLES.items()))
async def test_other_workspace_cannot_read(
    app: FastAPI, populated: tuple[Account, Account], table: str, column: str
) -> None:
    a, b = populated
    async with app.state.db.transaction(workspace_id=a.workspace_id, user_id=a.user_id) as session:
        own = (
            await session.execute(
                text(f"select count(*) from {table} where {column} = :ws"),
                {"ws": a.workspace_id},
            )
        ).scalar_one()
    assert own >= 1, f"fixture wrote nothing to {table}"
    async with app.state.db.transaction(workspace_id=b.workspace_id, user_id=b.user_id) as session:
        leaked = (
            await session.execute(
                text(f"select count(*) from {table} where {column} = :ws"),
                {"ws": a.workspace_id},
            )
        ).scalar_one()
    assert leaked == 0


async def test_users_visible_only_to_themselves(app: FastAPI, populated: tuple[Account, Account]) -> None:
    _, b = populated
    async with app.state.db.transaction(workspace_id=b.workspace_id, user_id=b.user_id) as session:
        rows = (await session.execute(text("select id from users"))).scalars().all()
    assert list(rows) == [b.user_id]


async def test_no_context_reads_nothing(app: FastAPI, populated: tuple[Account, Account]) -> None:
    async with app.state.db.transaction() as session:
        for table in [*TENANT_TABLES, "users"]:
            count = (await session.execute(text(f"select count(*) from {table}"))).scalar_one()
            assert count == 0, table


async def test_cannot_write_into_another_workspace(app: FastAPI, populated: tuple[Account, Account]) -> None:
    a, b = populated
    with pytest.raises(DBAPIError, match="row-level security"):
        async with app.state.db.transaction(workspace_id=b.workspace_id) as session:
            await service.post_transaction(
                session,
                workspace_id=a.workspace_id,
                type="adjustment",
                amount_usd=Decimal("100"),
                description="theft",
                external_ref=f"x_{new_id('txn')}",
            )


async def test_transaction_by_id_from_another_workspace_is_404(
    client: httpx.AsyncClient, populated: tuple[Account, Account]
) -> None:
    a, b = populated
    txn_id = (await client.get("/v1/billing/transactions", headers=a.headers)).json()["items"][0]["id"]
    assert (await client.get(f"/v1/billing/transactions/{txn_id}", headers=a.headers)).status_code == 200
    response = await client.get(f"/v1/billing/transactions/{txn_id}", headers=b.headers)
    assert response.status_code == 404
    assert response.json()["code"] == "not_found"


async def test_agent_and_version_of_another_workspace_are_404(
    client: httpx.AsyncClient, populated: tuple[Account, Account]
) -> None:
    a, b = populated
    agent = (await client.get("/v1/agents", headers=a.headers)).json()["items"][0]
    detail = (await client.get(f"/v1/agents/{agent['id']}", headers=a.headers)).json()
    version_id = detail["draft_version"]["id"]
    assert (await client.get(f"/v1/agents/{agent['id']}", headers=b.headers)).status_code == 404
    assert (
        await client.get(f"/v1/agents/{agent['id']}/versions/{version_id}", headers=b.headers)
    ).status_code == 404
    key = (await client.get("/v1/voices/ambient-audio", headers=a.headers)).json()["items"][0]["key"]
    assert (await client.delete(f"/v1/voices/ambient-audio?key={key}", headers=b.headers)).status_code == 404
