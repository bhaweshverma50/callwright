"""Prompt assistant money tests (T077, FR-037): one feature charge and one usage event per
successful request, charged once per Idempotency-Key, nothing on 402, 429 or 504."""

from __future__ import annotations

from decimal import Decimal

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select

from app.billing.models import CreditTransaction
from app.usage.models import UsageEvent
from tests.conftest import Account, signup
from tests.contract.test_prompt_ai_contract import drain

URL = "/v1/prompt-ai/generate"


def ask(text: str, **extra: object) -> dict[str, object]:
    return {"messages": [{"role": "user", "content": text}], **extra}


async def charges(app: FastAPI, account: Account) -> tuple[list[CreditTransaction], list[UsageEvent]]:
    async with app.state.db.transaction(workspace_id=account.workspace_id) as session:
        txns = (
            await session.execute(
                select(CreditTransaction).where(
                    CreditTransaction.workspace_id == account.workspace_id,
                    CreditTransaction.type == "feature_charge",
                )
            )
        ).scalars()
        events = (
            await session.execute(
                select(UsageEvent).where(
                    UsageEvent.workspace_id == account.workspace_id,
                    UsageEvent.feature_key == "prompt_generation",
                )
            )
        ).scalars()
        return list(txns), list(events)


async def test_one_charge_per_request_and_per_key(client: httpx.AsyncClient, app: FastAPI) -> None:
    account = await signup(client, app)
    agent = await client.post(
        "/v1/agents",
        json={"name": "A", "type": "single_prompt", "config": {"prompt": "x"}},
        headers=account.headers,
    )
    body = ask("A receptionist for a dental clinic", agent_id=agent.json()["id"])
    first = await client.post(URL, json=body, headers={**account.headers, "Idempotency-Key": "pa-1"})
    replay = await client.post(URL, json=body, headers={**account.headers, "Idempotency-Key": "pa-1"})
    assert first.status_code == replay.status_code == 200
    assert first.json() == replay.json()
    other = await client.post(URL, json=body, headers=account.headers)
    assert other.status_code == 200
    txns, events = await charges(app, account)
    assert len(txns) == 2 and len(events) == 2
    billed = Decimal(first.json()["billed_usd"])
    event = next(e for e in events if e.idempotency_key == "prompt_ai:pa-1")
    assert event.billable_cost_usd == billed and event.unit == "tokens" and event.quantity > 0
    assert event.raw_cost_usd < event.billable_cost_usd
    assert event.ref_type == "agent" and event.ref_id == agent.json()["id"]
    txn = next(t for t in txns if t.id == event.txn_id)
    assert txn.amount_usd == -billed and txn.feature_key == "prompt_generation"
    usage = (await client.get("/v1/usage", headers=account.headers)).json()
    assert "prompt_generation" in str(usage)


async def test_nothing_charged_on_402_429_504(
    client: httpx.AsyncClient, app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    account = await signup(client, app)
    timeout = await client.post(URL, json=ask("draft [timeout]"), headers=account.headers)
    assert timeout.status_code == 504
    error = await client.post(URL, json=ask("draft [error]"), headers=account.headers)
    assert error.status_code == 504
    monkeypatch.setattr(
        app.state, "settings", app.state.settings.model_copy(update={"prompt_ai_rate_limit_per_min": 0})
    )
    assert (await client.post(URL, json=ask("draft"), headers=account.headers)).status_code == 429
    assert await charges(app, account) == ([], [])
    monkeypatch.undo()

    broke = await signup(client, app)
    await drain(app, broke)
    assert (await client.post(URL, json=ask("draft"), headers=broke.headers)).status_code == 402
    assert await charges(app, broke) == ([], [])


async def test_proposal_based_on_current_prompt(client: httpx.AsyncClient, account: Account) -> None:
    current = {
        "prompt": "## Role\nYou book visits.\n- Ask the name\n- Ask the date\n- Confirm",
        "begin_message": None,
    }
    response = await client.post(
        URL, json=ask("make it more concise", current=current, language="en-US"), headers=account.headers
    )
    assert response.status_code == 200
    proposal = response.json()["proposal"]
    assert proposal and proposal["prompt"].startswith("## Role")
    reply_only = await client.post(URL, json=ask("hello [no proposal]"), headers=account.headers)
    assert reply_only.json()["proposal"] is None
    malformed = await client.post(URL, json=ask("draft [malformed]"), headers=account.headers)
    assert malformed.status_code == 200 and malformed.json()["proposal"] is None
