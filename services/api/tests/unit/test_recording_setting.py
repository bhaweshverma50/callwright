"""Recording setting at admission (003 T111, FR-043): workspace default times agent override."""

from __future__ import annotations

import psycopg
import pytest
from sqlalchemy import select

from app.calls import service as calls
from app.calls.models import Call
from tests.runtime_support import Runtime, agent_config, owner_sql


@pytest.mark.parametrize(
    ("workspace_default", "override", "enabled", "source"),
    [
        (True, "inherit", True, "workspace"),
        (False, "inherit", False, "workspace"),
        (True, "on", True, "agent"),
        (False, "on", True, "agent"),
        (True, "off", False, "agent"),
        (False, "off", False, "agent"),
        (True, None, True, "workspace"),  # missing override reads as inherit
        (False, "garbage", False, "workspace"),
    ],
)
def test_resolution_table(workspace_default: bool, override: str | None, enabled: bool, source: str) -> None:
    assert calls.resolve_recording(override, workspace_default) == (enabled, source)


async def _admit(runtime: Runtime, ws: str, recording: str | None) -> Call:
    advanced = {"recording": recording} if recording else {}
    config = agent_config()
    config["advanced"] = advanced
    agent = runtime.versions.add_agent(ws, config)
    admission = await calls.admit(
        runtime.db,
        calls.AdmissionRequest(ws, agent.agent_id, "web", "inbound", version="draft", origin="test"),
        catalog=runtime.catalog,
    )
    assert admission.admitted
    async with runtime.db.transaction(workspace_id=ws) as session:
        return (await session.execute(select(Call).where(Call.id == admission.call.id))).scalar_one()


async def test_admission_writes_setting_and_initial_status(runtime: Runtime) -> None:
    _, ws = await runtime.workspace()
    on = await _admit(runtime, ws, None)
    assert (on.recording_enabled, on.recording_setting_source, on.recording_status) == (
        True,
        "workspace",
        "none",
    )
    owner_sql("update workspaces set recording_default = false where id = %s", (ws,))
    off = await _admit(runtime, ws, "inherit")
    assert (off.recording_enabled, off.recording_setting_source, off.recording_status) == (
        False,
        "workspace",
        "not_recorded",
    )
    forced = await _admit(runtime, ws, "on")
    assert (forced.recording_enabled, forced.recording_setting_source) == (True, "agent")


async def test_setting_never_changes_after_admission(runtime: Runtime) -> None:
    _, ws = await runtime.workspace()
    call = await _admit(runtime, ws, "inherit")
    owner_sql("update workspaces set recording_default = false where id = %s", (ws,))
    async with runtime.db.transaction(workspace_id=ws) as session:
        again = (await session.execute(select(Call).where(Call.id == call.id))).scalar_one()
    assert again.recording_enabled and again.recording_setting_source == "workspace"
    with pytest.raises(psycopg.errors.CheckViolation):
        owner_sql("update calls set recording_enabled = false where id = %s", (call.id,))
    # not_recorded if and only if recording is off (calls_recording_consistency).
    with pytest.raises(psycopg.errors.CheckViolation):
        owner_sql("update calls set recording_status = 'not_recorded' where id = %s", (call.id,))
