"""Money test (003 T045, FR-007, FR-008): admission refusals in order, each stored as a failed call."""

from __future__ import annotations

from decimal import Decimal

import pytest
from callwright_contract.adapters import AdapterCatalog, AdapterEntry
from pydantic import SecretStr
from sqlalchemy import select

from app.calls import service as calls
from app.calls.models import Call
from app.core.errors import ProblemError
from tests.runtime_support import Runtime, agent_config, owner_sql


def request(ws: str, agent_id: str, **kw: object) -> calls.AdmissionRequest:
    args: dict[str, object] = {
        "workspace_id": ws,
        "agent_id": agent_id,
        "channel": "web",
        "direction": "inbound",
        "version": "draft",
        "origin": "test",
    }
    args.update(kw)
    return calls.AdmissionRequest(**args)  # type: ignore[arg-type]


async def stored(runtime: Runtime, ws: str, call_id: str) -> Call:
    async with runtime.db.transaction(workspace_id=ws) as session:
        call = (await session.execute(select(Call).where(Call.id == call_id))).scalar_one()
    return call


async def test_admits_a_funded_call(runtime: Runtime) -> None:
    _, ws = await runtime.workspace()
    agent = runtime.versions.add_agent(ws)
    admission = await calls.admit(runtime.db, request(ws, agent.agent_id), catalog=runtime.catalog)
    assert admission.admitted
    call = await stored(runtime, ws, admission.call.id)
    assert call.status == "queued" and call.disconnect_reason is None
    assert call.agent_version_id == agent.draft.version_id
    assert call.origin == "test" and call.is_test


@pytest.mark.parametrize("balance", ["0", "-0.25"])
async def test_refused_at_zero_or_below(runtime: Runtime, balance: str) -> None:
    _, ws = await runtime.workspace()
    await runtime.set_balance(ws, Decimal(balance))
    agent = runtime.versions.add_agent(ws)
    admission = await calls.admit(runtime.db, request(ws, agent.agent_id), catalog=runtime.catalog)
    assert not admission.admitted and admission.refusal is not None
    assert admission.refusal.code == "insufficient_credit" and admission.refusal.status == 402
    call = await stored(runtime, ws, admission.call.id)
    assert (call.status, call.disconnect_reason, call.billable_seconds) == (
        "failed",
        "insufficient_credit",
        0,
    )


async def test_email_unverified_is_checked_first(runtime: Runtime) -> None:
    user_id, ws = await runtime.workspace()
    owner_sql("update users set email_verified_at = null where id = %s", (user_id,))
    await runtime.set_balance(ws, Decimal(0))
    agent = runtime.versions.add_agent(ws, published=False)
    admission = await calls.admit(
        runtime.db, request(ws, agent.agent_id, version="published"), catalog=runtime.catalog
    )
    assert admission.refusal is not None and admission.refusal.code == "email_unverified"
    assert admission.refusal.status == 403
    call = await stored(runtime, ws, admission.call.id)
    assert (call.status, call.disconnect_reason, call.diagnostic) == ("failed", "error", "email_unverified")


async def test_unpublished_agent_on_published_selector(runtime: Runtime) -> None:
    _, ws = await runtime.workspace()
    agent = runtime.versions.add_agent(ws, published=False)
    admission = await calls.admit(
        runtime.db, request(ws, agent.agent_id, version="published"), catalog=runtime.catalog
    )
    assert admission.refusal is not None and admission.refusal.code == "agent_not_published"
    # Live channels always use the published version (FR-004).
    sip = await calls.admit(
        runtime.db,
        request(ws, agent.agent_id, channel="sip_inbound", version="draft", origin="live"),
        catalog=runtime.catalog,
    )
    assert sip.refusal is not None and sip.refusal.code == "agent_not_published"


async def test_unknown_agent_is_404_without_a_record(runtime: Runtime) -> None:
    _, ws = await runtime.workspace()
    other_ws = (await runtime.workspace())[1]
    foreign = runtime.versions.add_agent(other_ws)
    with pytest.raises(ProblemError) as err:
        await calls.admit(runtime.db, request(ws, foreign.agent_id), catalog=runtime.catalog)
    assert err.value.status == 404
    assert owner_sql("select count(*) from calls where workspace_id = %s", (ws,)) == [(0,)]


async def test_unsupported_vendor_names_the_vendor(runtime: Runtime) -> None:
    _, ws = await runtime.workspace()
    agent = runtime.versions.add_agent(
        ws, agent_config(tts={"provider": "acme", "model": "x", "voice_id": "v"})
    )
    admission = await calls.admit(runtime.db, request(ws, agent.agent_id), catalog=runtime.catalog)
    assert admission.refusal is not None and admission.refusal.status == 422
    assert admission.refusal.diagnostic == "unsupported_vendor:tts/acme"


def with_key(monkeypatch: pytest.MonkeyPatch, key: SecretStr | None) -> None:
    settings = calls.get_settings().model_copy(update={"anthropic_api_key": key})
    monkeypatch.setattr(calls, "get_settings", lambda: settings)


CLAUDE = {"provider": "anthropic", "model": "claude-haiku-5-5", "temperature": 1.0}


async def test_anthropic_without_a_key_is_refused(runtime: Runtime, monkeypatch: pytest.MonkeyPatch) -> None:
    """003 T069: no ANTHROPIC_API_KEY on the deployment, so live calls are refused up front."""
    with_key(monkeypatch, None)
    _, ws = await runtime.workspace()
    agent = runtime.versions.add_agent(ws, agent_config(llm=CLAUDE))
    admission = await calls.admit(runtime.db, request(ws, agent.agent_id), catalog=runtime.catalog)
    assert admission.refusal is not None and admission.refusal.code == "unsupported_vendor"
    assert admission.refusal.diagnostic == "unsupported_vendor:llm/anthropic"


async def test_anthropic_with_a_key_is_admitted_and_priced(
    runtime: Runtime, monkeypatch: pytest.MonkeyPatch
) -> None:
    with_key(monkeypatch, SecretStr("sk-ant"))
    _, ws = await runtime.workspace()
    agent = runtime.versions.add_agent(ws, agent_config(llm=CLAUDE))
    admission = await calls.admit(runtime.db, request(ws, agent.agent_id), catalog=runtime.catalog)
    assert admission.admitted, admission.refusal


async def test_unpriced_configuration_is_refused(runtime: Runtime) -> None:
    """A vendor the worker supports but the pricing catalog does not price."""
    _, ws = await runtime.workspace()
    catalog = AdapterCatalog((*runtime.catalog.entries, AdapterEntry("tts", "newvoice", ("v1",))))
    agent = runtime.versions.add_agent(ws, agent_config(tts={"provider": "newvoice", "model": "v1"}))
    admission = await calls.admit(runtime.db, request(ws, agent.agent_id), catalog=catalog)
    assert admission.refusal is not None and admission.refusal.code == "pricing_unavailable"
    assert admission.refusal.diagnostic == "pricing_unavailable:tts"
    call = await stored(runtime, ws, admission.call.id)
    assert call.status == "failed" and call.diagnostic == "pricing_unavailable:tts"


async def test_auto_stt_language_without_a_model_is_refused(runtime: Runtime) -> None:
    _, ws = await runtime.workspace()
    agent = runtime.versions.add_agent(
        ws, agent_config(language="ja", stt={"provider": "assemblyai", "model": None})
    )
    admission = await calls.admit(runtime.db, request(ws, agent.agent_id), catalog=runtime.catalog)
    assert admission.refusal is not None
    assert admission.refusal.diagnostic == "stt_language_unsupported:assemblyai/ja"


COMPILED_FLOW = {"compiled": {"schema_version": 1}}


async def test_flow_agent_without_a_compiled_flow_is_refused(runtime: Runtime) -> None:
    _, ws = await runtime.workspace()
    agent = runtime.versions.add_agent(ws, agent_type="flow")
    admission = await calls.admit(runtime.db, request(ws, agent.agent_id), catalog=runtime.catalog)
    assert admission.refusal is not None and admission.refusal.code == "flow_not_compiled"
    assert admission.refusal.status == 409


async def test_concurrency_limit(runtime: Runtime) -> None:
    _, ws = await runtime.workspace(concurrency=1)
    agent = runtime.versions.add_agent(ws)
    first = await calls.admit(runtime.db, request(ws, agent.agent_id), catalog=runtime.catalog)
    second = await calls.admit(runtime.db, request(ws, agent.agent_id), catalog=runtime.catalog)
    assert first.admitted
    assert second.refusal is not None and second.refusal.code == "concurrency_limit"
    assert second.refusal.status == 429 and second.refusal.disconnect_reason == "concurrency_limit"
    # Refused calls never hold a slot: ending the first frees it.
    owner_sql("update calls set status = 'failed' where id = %s", (first.call.id,))
    assert (await calls.admit(runtime.db, request(ws, agent.agent_id), catalog=runtime.catalog)).admitted


async def test_refusal_sends_only_call_ended(runtime: Runtime) -> None:
    _, ws = await runtime.workspace()
    await runtime.set_balance(ws, Decimal(0))
    agent = runtime.versions.add_agent(
        ws, agent_config(advanced={"webhook_url": "https://hooks.example.com/in"})
    )
    admission = await calls.admit(runtime.db, request(ws, agent.agent_id), catalog=runtime.catalog)
    assert [j.name for j in admission.deferred.jobs] == ["deliver_webhook"]
    rows = owner_sql("select event from webhook_deliveries where call_id = %s", (admission.call.id,))
    assert rows == [("call_ended",)]


async def test_idempotency_key_returns_the_same_call(runtime: Runtime) -> None:
    _, ws = await runtime.workspace()
    agent = runtime.versions.add_agent(ws)
    first = await calls.admit(
        runtime.db, request(ws, agent.agent_id, idempotency_key="k-1"), catalog=runtime.catalog
    )
    again = await calls.admit(
        runtime.db, request(ws, agent.agent_id, idempotency_key="k-1"), catalog=runtime.catalog
    )
    assert again.call.id == first.call.id and not again.created and again.admitted
