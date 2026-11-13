"""The account erase job: data gone, ledger kept, trial claim kept, safe to re-run."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import httpx
import psycopg
from fastapi import FastAPI

from app.account.erase import EraseDeps, erase_due
from app.core.secrets import key_wrapper
from app.knowledge.sources.fake_drive import FakeDriveClient
from app.workspaces.service import normalized_email
from tests.conftest import PASSWORD, Account, make_client, signup
from tests.connector_helpers import connect, fake_drive  # noqa: F401
from tests.fakes.livekit_fake import Channels
from tests.runtime_support import _owner_dsn, owner_sql

KEPT = ("credit_transactions", "usage_events", "checkout_sessions", "call_costs")


class Recorder:
    def __init__(self) -> None:
        self.keys: list[str] = []

    async def __call__(self, keys: Sequence[str]) -> None:
        self.keys.extend(keys)


def _deps(app: FastAPI, channels: Channels, drive: FakeDriveClient, recorder: Recorder) -> EraseDeps:
    state = app.state
    return EraseDeps(
        db=state.db,
        settings=state.settings,
        store=state.storage,
        sip=channels.sip,
        drive=drive,
        graph=channels.graph,
        idp=state.idp,
        delete_recordings=recorder,
        wrapper=key_wrapper(state.settings),
    )


def _tenant_rows(workspace_id: str) -> dict[str, int]:
    """Row counts per tenant table (every table with a workspace_id column) for one workspace."""
    with psycopg.connect(_owner_dsn(), autocommit=True) as conn:
        tables = [
            r[0]
            for r in conn.execute(
                "select c.relname from pg_class c join pg_namespace n on n.oid = c.relnamespace "
                "join pg_attribute a on a.attrelid = c.oid and a.attname = 'workspace_id' "
                "where n.nspname = 'public' and c.relkind = 'r' order by 1"
            )
        ]
        found = {}
        for table in tables:
            row = conn.execute(f'select count(*) from "{table}" where workspace_id = %s', (workspace_id,))
            count = row.fetchone()
            assert count is not None
            if count[0]:
                found[table] = count[0]
    return found


async def _account_with_data(
    client: httpx.AsyncClient, app: FastAPI, channels: Channels
) -> tuple[Account, dict[str, Any]]:
    from app.dev.seed_calls import seed
    from tests.agent_helpers import create_ok

    account = await signup(client, app)
    ws = account.workspace_id
    with psycopg.connect(_owner_dsn(), autocommit=True) as conn:
        seed(conn, ws)
    owner_sql(
        "update calls set status = 'ended', ended_at = coalesce(ended_at, now()) "
        "where workspace_id = %s and status in ('queued', 'ringing', 'in_progress')",
        (ws,),
    )
    await create_ok(client, account, name="Clinic desk")
    agent = channels.agent(ws)
    number = await channels.number(client, account, inbound_agent_id=agent, outbound_agent_id=agent)
    connection = await connect(client, account)
    # The fake Drive gives every connection the same Google account; a unique one here keeps other
    # tests' connections from making this account's grant look shared.
    owner_sql(
        "update connections set account_subject = 'sub-' || workspace_id where workspace_id = %s", (ws,)
    )
    owner_sql(
        "update calls set recording_key = 'recordings/' || workspace_id || '/' || id || '.mp4' "
        "where workspace_id = %s and recording_key is null",
        (ws,),
    )
    return account, {"number": number, "connection": connection}


def _due(account: Account) -> None:
    owner_sql(
        "update users set deletion_requested_at = now() - interval '31 days', "
        "deletion_scheduled_at = now() - interval '1 day' where id = %s",
        (account.user_id,),
    )


async def test_erase_removes_data_keeps_ledger_and_trial_claim(
    app: FastAPI,
    channels: Channels,
    fake_drive: FakeDriveClient,  # noqa: F811
) -> None:
    async with make_client(app, "10.7.2.1") as client:
        account, _ = await _account_with_data(client, app, channels)
        ws = account.workspace_id
        before = _tenant_rows(ws)
        assert before.get("calls", 0) > 0 and before.get("agents", 0) > 0
        assert before.get("phone_numbers") == 1 and before.get("connections") == 1
        ledger = {t: before.get(t, 0) for t in KEPT}
        assert ledger["credit_transactions"] > 0 and ledger["call_costs"] > 0
        assert len(channels.sip.inbound) == 1
        keys = [
            r[0]
            for r in owner_sql(
                "select recording_key from calls where workspace_id = %s and recording_key is not null", (ws,)
            )
        ]
        assert keys

        # Not due yet: nothing happens.
        recorder = Recorder()
        deps = _deps(app, channels, fake_drive, recorder)
        await erase_due(deps)
        assert _tenant_rows(ws) == before

        _due(account)
        result = await erase_due(deps)
        assert result["erased"] >= 1 and result["failed"] == 0 and result["deferred"] == 0

        # Data gone.
        left = _tenant_rows(ws)
        assert set(left) <= set(KEPT), left
        assert {t: left.get(t, 0) for t in KEPT} == ledger
        assert owner_sql("select count(*) from users where id = %s", (account.user_id,)) == [(0,)]
        assert owner_sql("select count(*) from local_idp.users where email = %s", (account.email,)) == [(0,)]
        # Tombstone workspace: no name, no owner.
        assert owner_sql(
            "select name, owner_user_id, deleted_at is not null from workspaces where id = %s", (ws,)
        ) == [("[deleted]", None, True)]
        # The ledger holds no email.
        assert owner_sql(
            "select count(*) from credit_transactions where workspace_id = %s and description ilike %s",
            (ws, f"%{account.email.split('@')[0]}%"),
        ) == [(0,)]
        # Recordings and SIP objects.
        assert sorted(recorder.keys) == sorted(keys)
        assert channels.sip.inbound == {} and channels.sip.outbound == {} and channels.sip.rules == {}
        # The Google grant was revoked at Google.
        assert fake_drive.revoked_tokens
        # The login is gone.
        gone = await client.post("/v1/auth/sign-in", json={"email": account.email, "password": PASSWORD})
        assert gone.status_code == 401
        assert (await client.get("/v1/me", headers=account.headers)).status_code == 401

        # Re-running changes nothing and finds nothing due for this account.
        again = await erase_due(deps)
        assert again["failed"] == 0
        assert _tenant_rows(ws) == left
        assert owner_sql("select count(*) from workspaces where id = %s", (ws,)) == [(1,)]

        # The trial claim survives: signing up again with the same mailbox gets no new credit.
        claim = await app.state.redis.get(f"trial_claimed:{normalized_email(account.email)}")
        assert claim is not None
        again_account = await signup(client, app, email=account.email)
        assert again_account.workspace_id != ws
        me = (await client.get("/v1/me", headers=again_account.headers)).json()
        assert float(me["balance_usd"]) == 0.0
        assert owner_sql(
            "select count(*) from credit_transactions where workspace_id = %s and type = 'trial_grant'",
            (again_account.workspace_id,),
        ) == [(0,)]


async def test_account_with_an_active_call_waits(
    app: FastAPI,
    channels: Channels,
    fake_drive: FakeDriveClient,  # noqa: F811
) -> None:
    async with make_client(app, "10.7.2.2") as client:
        account, _ = await _account_with_data(client, app, channels)
        ws = account.workspace_id
        owner_sql(
            "update calls set status = 'in_progress' "
            "where id = (select id from calls where workspace_id = %s limit 1)",
            (ws,),
        )
        _due(account)
        result = await erase_due(_deps(app, channels, fake_drive, Recorder()))
        assert result["deferred"] >= 1
        assert owner_sql("select count(*) from users where id = %s", (account.user_id,)) == [(1,)]
        assert _tenant_rows(ws).get("calls", 0) > 0

        owner_sql(
            "update calls set status = 'ended' where workspace_id = %s and status = 'in_progress'", (ws,)
        )
        result = await erase_due(_deps(app, channels, fake_drive, Recorder()))
        assert result["failed"] == 0
        assert owner_sql("select count(*) from users where id = %s", (account.user_id,)) == [(0,)]


async def test_a_failure_keeps_the_account_for_the_next_run(
    app: FastAPI,
    channels: Channels,
    fake_drive: FakeDriveClient,  # noqa: F811
) -> None:
    async with make_client(app, "10.7.2.3") as client:
        account, _ = await _account_with_data(client, app, channels)
        _due(account)

        class Failing(Recorder):
            async def __call__(self, keys: Sequence[str]) -> None:
                raise RuntimeError("storage down")

        deps = _deps(app, channels, fake_drive, Failing())
        result = await erase_due(deps)
        assert result["deferred"] >= 1 and result["erased"] == 0
        assert owner_sql("select count(*) from users where id = %s", (account.user_id,)) == [(1,)]

        result = await erase_due(_deps(app, channels, fake_drive, Recorder()))
        assert result["failed"] == 0
        assert owner_sql("select count(*) from users where id = %s", (account.user_id,)) == [(0,)]


async def test_a_google_account_shared_with_another_workspace_is_not_revoked(
    app: FastAPI,
    channels: Channels,
    fake_drive: FakeDriveClient,  # noqa: F811
) -> None:
    async with make_client(app, "10.7.2.4") as client:
        leaving = await signup(client, app)
        staying = await signup(client, app)
        await connect(client, leaving)
        await connect(client, staying)  # the fake Drive: the same Google account for both
        _due(leaving)
        result = await erase_due(_deps(app, channels, fake_drive, Recorder()))
        assert result["failed"] == 0
        assert fake_drive.revoked_tokens == []
        assert owner_sql("select count(*) from users where id = %s", (leaving.user_id,)) == [(0,)]
        assert _tenant_rows(staying.workspace_id).get("connections") == 1
