"""Guarded call transitions (003 T048): the first writer wins, a forbidden move is a bug."""

from __future__ import annotations

import pytest
from fastapi import FastAPI

from app.calls.models import Call, transition
from tests.conftest import make_workspace
from tests.runtime_support import insert_call


async def _call(app: FastAPI, status: str) -> tuple[str, str]:
    _, ws = await make_workspace(app)
    call_id = insert_call(ws, status=status)
    return ws, call_id


async def test_first_writer_wins_the_disconnect_reason(app: FastAPI) -> None:
    ws, call_id = await _call(app, "in_progress")
    async with app.state.db.transaction(workspace_id=ws) as session:
        assert await transition(session, call_id, "in_progress", "ended", disconnect_reason="user_hangup")
    async with app.state.db.transaction(workspace_id=ws) as session:
        assert not await transition(session, call_id, "in_progress", "ended", disconnect_reason="error")
        call = await session.get(Call, call_id)
        assert call is not None and call.status == "ended" and call.disconnect_reason == "user_hangup"


async def test_forbidden_transition_raises(app: FastAPI) -> None:
    ws, call_id = await _call(app, "completed")
    async with app.state.db.transaction(workspace_id=ws) as session:
        with pytest.raises(ValueError, match="forbidden"):
            await transition(session, call_id, "completed", "in_progress")
