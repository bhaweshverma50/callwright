"""Call state machine (003 T048): allowed and forbidden transitions, first writer wins."""

from __future__ import annotations

import itertools

import pytest
from fastapi import FastAPI

from app.calls.models import CALL_STATUSES, Call, can_transition, sources_for, transition
from app.core.ids import new_id
from tests.conftest import make_workspace

ALLOWED = {
    (None, "queued"),
    (None, "failed"),
    ("queued", "ringing"),
    ("queued", "in_progress"),
    ("ringing", "in_progress"),
    ("ringing", "no_answer"),
    ("ringing", "busy"),
    ("queued", "failed"),
    ("ringing", "failed"),
    ("in_progress", "ended"),
    ("ended", "processing"),
    ("processing", "completed"),
    ("processing", "voicemail"),
}


@pytest.mark.parametrize(("current", "new"), sorted(ALLOWED, key=str))
def test_allowed(current: str | None, new: str) -> None:
    assert can_transition(current, new)


def test_everything_else_is_forbidden() -> None:
    for current, new in itertools.product((None, *CALL_STATUSES), CALL_STATUSES):
        assert can_transition(current, new) == ((current, new) in ALLOWED), (current, new)


def test_terminal_states_have_no_exit() -> None:
    for terminal in ("completed", "failed", "no_answer", "busy", "voicemail"):
        assert not any(can_transition(terminal, new) for new in CALL_STATUSES)


def test_sources_for() -> None:
    assert sources_for("failed") == ("queued", "ringing")
    assert sources_for("in_progress") == ("queued", "ringing")


async def _call(app: FastAPI, status: str) -> tuple[str, str]:
    _, ws = await make_workspace(app)
    call_id = new_id("call")
    async with app.state.db.transaction(workspace_id=ws) as session:
        session.add(
            Call(
                id=call_id,
                workspace_id=ws,
                agent_id=new_id("agt"),
                channel="web",
                direction="inbound",
                status=status,
                recording_enabled=True,
                recording_status="none",
            )
        )
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
