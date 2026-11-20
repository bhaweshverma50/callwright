"""Scheduled syncs stop while the owner's account waits to be deleted (account deletion, 022)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
from fastapi import FastAPI

from app.knowledge.sources.fake_drive import FakeDriveClient
from tests.conftest import Account
from tests.connector_helpers import connect, fake_drive, make_kb, sync_now, synced_source
from tests.contract.test_knowledge_contract import fake_embedder
from tests.runtime_support import owner_sql

__all__ = ["fake_drive", "fake_embedder"]


def _source(source_id: str) -> tuple[str, str | None, datetime]:
    [(state, reason, next_at)] = owner_sql(
        "select state, attention_reason, next_sync_at from kb_sources where id = %s", (source_id,)
    )
    return state, reason, next_at


def _scheduled_runs(source_id: str) -> int:
    [(count,)] = owner_sql(
        "select count(*) from kb_sync_runs where source_id = %s and trigger = 'scheduled'", (source_id,)
    )
    return int(count)


async def test_scheduled_syncs_stop_while_deletion_is_scheduled(
    client: httpx.AsyncClient, app: FastAPI, account: Account, fake_drive: FakeDriveClient
) -> None:
    root = fake_drive.seed("property")["Listings"]
    conn = await connect(client, account)
    kb_id = await make_kb(client, account)
    source = await synced_source(client, account, kb_id, conn["id"], root)
    owner_sql(
        "update users set deletion_scheduled_at = now() + interval '30 days' where id = %s",
        (account.user_id,),
    )
    calls_before = fake_drive.calls

    assert await sync_now(app, source["id"], "scheduled") is None
    state, reason, next_at = _source(source["id"])
    assert (state, reason) == ("healthy", None)  # nobody can see the source; its state is left alone
    assert next_at > datetime.now(UTC) + timedelta(minutes=55)
    assert _scheduled_runs(source["id"]) == 0, "a scheduled run was recorded for a locked account"
    assert fake_drive.calls == calls_before, "Drive was called for a locked account"

    # Keep my account: the next scheduled sync runs again.
    owner_sql("update users set deletion_scheduled_at = null where id = %s", (account.user_id,))
    assert await sync_now(app, source["id"], "scheduled")
    assert _scheduled_runs(source["id"]) == 1
