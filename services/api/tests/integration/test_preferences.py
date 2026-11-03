"""Per-user preferences (013): defaults, partial saves, validation and isolation (FR-001)."""

from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from tests.conftest import Account, signup

URL = "/v1/me/preferences"


async def _patch(client: httpx.AsyncClient, account: Account, onboarding: object) -> httpx.Response:
    return await client.patch(URL, json={"onboarding": onboarding}, headers=account.headers)


async def test_defaults_until_first_save(client: httpx.AsyncClient, account: Account) -> None:
    got = await client.get(URL, headers=account.headers)
    assert got.status_code == 200
    assert got.json()["onboarding"] == {"status": "not_started", "step": None, "updated_at": None}


async def test_partial_updates_keep_other_fields(client: httpx.AsyncClient, account: Account) -> None:
    first = await _patch(client, account, {"status": "in_progress", "step": "agents"})
    assert first.status_code == 200, first.text
    assert first.json()["onboarding"]["updated_at"] is not None

    moved = await _patch(client, account, {"step": "test-call"})
    assert moved.json()["onboarding"] == {
        **moved.json()["onboarding"],
        "status": "in_progress",
        "step": "test-call",
    }

    skipped = await _patch(client, account, {"status": "skipped"})
    assert skipped.json()["onboarding"]["status"] == "skipped"
    assert skipped.json()["onboarding"]["step"] == "test-call"

    cleared = await _patch(client, account, {"status": "completed", "step": None})
    assert cleared.json()["onboarding"]["step"] is None

    # Restart: any status can follow any other.
    again = await _patch(client, account, {"status": "in_progress", "step": "agents"})
    assert again.json()["onboarding"]["status"] == "in_progress"
    read = await client.get(URL, headers=account.headers)
    assert read.json()["onboarding"]["step"] == "agents"


async def test_first_save_with_step_only_starts_not_started(
    client: httpx.AsyncClient, account: Account
) -> None:
    saved = await _patch(client, account, {"step": "agents"})
    assert saved.json()["onboarding"]["status"] == "not_started"


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"onboarding": {}},
        {"onboarding": {"status": None}},
        {"onboarding": {"status": "paused"}},
        {"onboarding": {"step": "Agents"}},
        {"onboarding": {"step": "a" * 41}},
        {"onboarding": {"step": "agents; drop table"}},
        {"onboarding": {"status": "skipped", "extra": 1}},
        {"onboarding": {"status": "skipped"}, "theme": "dark"},
    ],
)
async def test_validation(client: httpx.AsyncClient, account: Account, body: dict[str, object]) -> None:
    res = await client.patch(URL, json=body, headers=account.headers)
    assert res.status_code == 422, res.text
    assert res.headers["content-type"].startswith("application/problem+json")


async def test_auth_required(client: httpx.AsyncClient) -> None:
    assert (await client.get(URL)).status_code == 401
    assert (await client.patch(URL, json={"onboarding": {"status": "skipped"}})).status_code == 401
    bad = {"Authorization": "Bearer not-a-token"}
    assert (await client.get(URL, headers=bad)).status_code == 401


async def test_each_user_sees_only_their_own(client: httpx.AsyncClient, app: FastAPI) -> None:
    a = await signup(client, app)
    b = await signup(client, app)
    await _patch(client, a, {"status": "completed", "step": "done"})
    read_b = await client.get(URL, headers=b.headers)
    assert read_b.json()["onboarding"]["status"] == "not_started"
    await _patch(client, b, {"status": "skipped", "step": "voice"})
    read_a = await client.get(URL, headers=a.headers)
    assert read_a.json()["onboarding"] == {
        **read_a.json()["onboarding"],
        "status": "completed",
        "step": "done",
    }


async def test_rls_blocks_other_users_rows(client: httpx.AsyncClient, app: FastAPI) -> None:
    a = await signup(client, app)
    b = await signup(client, app)
    await _patch(client, a, {"status": "in_progress", "step": "agents"})
    db = app.state.db

    # B's context cannot read A's row, even by id.
    async with db.transaction(workspace_id=b.workspace_id, user_id=b.user_id) as session:
        rows = (
            await session.execute(
                text("select user_id from user_preferences where user_id = :u"), {"u": a.user_id}
            )
        ).all()
        assert rows == []
    # A's user id with B's workspace sees nothing either (both settings must match).
    async with db.transaction(workspace_id=b.workspace_id, user_id=a.user_id) as session:
        assert (await session.execute(text("select count(*) from user_preferences"))).scalar_one() == 0
    # No context at all sees nothing.
    async with db.transaction() as session:
        assert (await session.execute(text("select count(*) from user_preferences"))).scalar_one() == 0

    # B cannot write a row for A, nor change A's row.
    with pytest.raises(DBAPIError):
        async with db.transaction(workspace_id=b.workspace_id, user_id=b.user_id) as session:
            await session.execute(
                text(
                    "insert into user_preferences (user_id, workspace_id, onboarding_status) "
                    "values (:u, :w, 'skipped')"
                ),
                {"u": a.user_id, "w": a.workspace_id},
            )
    async with db.transaction(workspace_id=b.workspace_id, user_id=b.user_id) as session:
        changed = await session.execute(
            text("update user_preferences set onboarding_status = 'skipped' where user_id = :u"),
            {"u": a.user_id},
        )
        assert changed.rowcount == 0
    still = await client.get(URL, headers=a.headers)
    assert still.json()["onboarding"]["status"] == "in_progress"
