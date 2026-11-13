"""While deletion is scheduled the workspace takes no calls at all, so it spends no credit."""

from __future__ import annotations

from app.calls import service as calls
from tests.runtime_support import Runtime, owner_sql


async def test_calls_are_refused_while_deletion_is_scheduled(runtime: Runtime) -> None:
    user_id, ws = await runtime.workspace()
    agent = runtime.versions.add_agent(ws)
    request = calls.AdmissionRequest(ws, agent.agent_id, "web", "inbound", version="draft", origin="test")

    owner_sql("update users set deletion_scheduled_at = now() + interval '30 days' where id = %s", (user_id,))
    refused = await calls.admit(runtime.db, request, catalog=runtime.catalog)
    assert not refused.admitted
    assert refused.refusal is not None and refused.refusal.code == "account_deletion_scheduled"
    assert refused.refusal.status == 403

    # Keep my account: calls work again with nothing else to undo.
    owner_sql("update users set deletion_scheduled_at = null where id = %s", (user_id,))
    assert (await calls.admit(runtime.db, request, catalog=runtime.catalog)).admitted
