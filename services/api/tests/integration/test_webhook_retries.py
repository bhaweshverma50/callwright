"""Webhook delivery (003 T087, US5, FR-038, FR-039): retry schedule, non-retryable 400 and 410,
timeouts, blocked private targets and manual redelivery, against a real local receiver."""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from app.calls.effects import Deferred
from app.webhooks_out import jobs, service
from tests.integration.tools.flaky_receiver import FlakyReceiver, verify
from tests.runtime_support import Runtime, admitted_call, agent_config, owner_sql


@pytest.fixture
def receiver_factory() -> Iterator[Any]:
    started: list[FlakyReceiver] = []

    def make(**kw: Any) -> FlakyReceiver:
        receiver = FlakyReceiver(**kw).start()
        started.append(receiver)
        return receiver

    yield make
    for receiver in started:
        receiver.stop()


async def _delivery(runtime: Runtime, url: str, timeout_ms: int = 3000) -> tuple[str, str]:
    setup = await admitted_call(
        runtime, config=agent_config(advanced={"webhook_url": url, "webhook_timeout_ms": timeout_ms})
    )
    async with runtime.db.transaction(workspace_id=setup.workspace_id) as session:
        from app.calls.models import Call

        call = await session.get(Call, setup.call_id)
        assert call is not None
        delivery_id = await service.enqueue_event(
            session,
            call,
            "call_ended",
            config=runtime.versions.versions[call.agent_version_id or ""].config,
            deferred=Deferred(),
        )
    assert delivery_id is not None
    return setup.workspace_id, delivery_id


def _settings(app: FastAPI) -> Any:
    return app.state.settings.model_copy(update={"webhooks_allow_http": True, "webhooks_allow_private": True})


async def _attempt(app: FastAPI, runtime: Runtime, ws: str, delivery_id: str) -> jobs.DeliveryOutcome:
    async with httpx.AsyncClient() as http:
        return await jobs.deliver(runtime.db, _settings(app), http, runtime.queue, ws, delivery_id)


async def test_fails_twice_then_succeeds_with_valid_signatures(
    app: FastAPI, runtime: Runtime, receiver_factory: Any
) -> None:
    receiver = receiver_factory(fail=2)
    ws, delivery_id = await _delivery(runtime, receiver.url)
    first = await _attempt(app, runtime, ws, delivery_id)
    assert first.status == "pending" and first.retry_in_s is not None and 9 <= first.retry_in_s <= 11
    scheduled = runtime.queue.jobs[-1]
    assert (scheduled.name, scheduled.args, scheduled.job_id) == (
        "deliver_webhook",
        (ws, delivery_id),
        f"{delivery_id}:2",
    )
    second = await _attempt(app, runtime, ws, delivery_id)
    assert second.status == "pending" and second.retry_in_s is not None and 54 <= second.retry_in_s <= 66
    third = await _attempt(app, runtime, ws, delivery_id)
    assert third.status == "succeeded"
    attempts = owner_sql("select attempts, status from webhook_deliveries where id = %s", (delivery_id,))[0]
    assert [a["status_code"] for a in attempts[0]] == [500, 500, 200] and attempts[1] == "succeeded"
    assert attempts[0][0]["response_excerpt"] == "nope"
    # Every attempt verifies with the workspace secret; the body is identical each time.
    async with runtime.db.transaction(workspace_id=ws) as session:
        secret = (await service.signing_secrets(session, service.key_wrapper(app.state.settings), ws))[0]
    bodies = {r.body for r in receiver.received}
    assert len(bodies) == 1 and len(receiver.received) == 3
    for item in receiver.received:
        assert verify(secret, item.headers["Callwright-Signature"], item.body)
        assert item.headers["Callwright-Event"] == "call_ended"
        assert item.headers["Callwright-Delivery"] == delivery_id
        assert item.headers["User-Agent"] == "Callwright-Webhooks/1"
    # A final delivery is never sent again.
    assert (await _attempt(app, runtime, ws, delivery_id)).status == "succeeded"
    assert len(receiver.received) == 3


@pytest.mark.parametrize("status", [400, 410])
async def test_non_retryable_status_fails_at_once(
    app: FastAPI, runtime: Runtime, receiver_factory: Any, status: int
) -> None:
    receiver = receiver_factory(fail=5, fail_status=status)
    ws, delivery_id = await _delivery(runtime, receiver.url)
    outcome = await _attempt(app, runtime, ws, delivery_id)
    assert outcome.status == "failed" and outcome.retry_in_s is None
    assert outcome.attempt is not None and outcome.attempt["status_code"] == status


@pytest.mark.parametrize("status", [408, 429, 503])
async def test_retryable_statuses(app: FastAPI, runtime: Runtime, receiver_factory: Any, status: int) -> None:
    receiver = receiver_factory(fail=1, fail_status=status)
    ws, delivery_id = await _delivery(runtime, receiver.url)
    assert (await _attempt(app, runtime, ws, delivery_id)).status == "pending"


async def test_timeout_is_recorded_and_retried(app: FastAPI, runtime: Runtime, receiver_factory: Any) -> None:
    receiver = receiver_factory(fail=0, delay_s=1.6)
    ws, delivery_id = await _delivery(runtime, receiver.url, timeout_ms=1000)
    outcome = await _attempt(app, runtime, ws, delivery_id)
    assert outcome.status == "pending" and outcome.attempt is not None
    assert outcome.attempt["error"] == "timeout"


async def test_gives_up_after_six_attempts(app: FastAPI, runtime: Runtime, receiver_factory: Any) -> None:
    receiver = receiver_factory(fail=100)
    ws, delivery_id = await _delivery(runtime, receiver.url)
    statuses = [(await _attempt(app, runtime, ws, delivery_id)).status for _ in range(7)]
    assert statuses == ["pending"] * 5 + ["failed", "failed"]
    assert len(receiver.received) == 6
    delays = [j.defer_by_s for j in runtime.queue.jobs if j.args == (ws, delivery_id)]
    expected = [10, 60, 300, 1800, 7200]
    assert len(delays) == 5
    assert all(0.9 * e <= (d or 0) <= 1.1 * e for d, e in zip(delays, expected, strict=True))


async def test_connection_error_and_blocked_target(app: FastAPI, runtime: Runtime) -> None:
    ws, delivery_id = await _delivery(runtime, "http://127.0.0.1:1/closed")
    outcome = await _attempt(app, runtime, ws, delivery_id)
    assert outcome.attempt is not None and outcome.attempt["error"] == "connection_error"
    assert outcome.status == "pending"
    # With the production guard (no private targets) the same URL is blocked, not retried.
    ws2, blocked_id = await _delivery(runtime, "https://10.0.0.5/hook")
    async with httpx.AsyncClient() as http:
        blocked = await jobs.deliver(runtime.db, app.state.settings, http, runtime.queue, ws2, blocked_id)
    assert blocked.status == "blocked" and blocked.attempt is not None
    assert blocked.attempt["error"] == "url_not_allowed"


async def test_manual_redelivery_sends_the_same_body_again(
    app: FastAPI, runtime: Runtime, receiver_factory: Any
) -> None:
    receiver = receiver_factory(fail=0)
    ws, delivery_id = await _delivery(runtime, receiver.url)
    assert (await _attempt(app, runtime, ws, delivery_id)).status == "succeeded"
    deferred = Deferred()
    async with runtime.db.transaction(workspace_id=ws) as session:
        copy = await service.redeliver(session, ws, delivery_id, deferred)
    assert copy is not None and deferred.jobs[0].args == (ws, copy.id)
    assert (await _attempt(app, runtime, ws, copy.id)).status == "succeeded"
    first, second = receiver.received
    assert first.body == second.body
    assert json.loads(second.body)["event_id"] == json.loads(first.body)["event_id"]
    assert second.headers["Callwright-Delivery"] == copy.id


async def test_rotation_overlap_signs_with_both_secrets(
    app: FastAPI, runtime: Runtime, receiver_factory: Any
) -> None:
    receiver = receiver_factory(fail=0)
    ws, delivery_id = await _delivery(runtime, receiver.url)
    wrapper = service.key_wrapper(app.state.settings)
    async with runtime.db.transaction(workspace_id=ws) as session:
        old = (await service.signing_secrets(session, wrapper, ws))[0]
        new = (await service.rotate_secret(session, wrapper, ws)).secret
    await _attempt(app, runtime, ws, delivery_id)
    header = receiver.received[0].headers["Callwright-Signature"]
    assert header.count("v1=") == 2
    assert new is not None and verify(new, header, receiver.received[0].body)
    assert verify(old, header, receiver.received[0].body)
    async with runtime.db.transaction(workspace_id=ws) as session:
        later = await service.signing_secrets(session, wrapper, ws, now=datetime(2099, 1, 1, tzinfo=UTC))
    assert later == [new]


async def test_purge_drops_deliveries_older_than_30_days(app: FastAPI, runtime: Runtime) -> None:
    _, delivery_id = await _delivery(runtime, "https://hooks.example.com/x")
    owner_sql(
        "update webhook_deliveries set created_at = now() - interval '31 days' where id = %s", (delivery_id,)
    )
    purged = await jobs.purge_webhook_deliveries(runtime.ctx())
    assert purged >= 1
    assert owner_sql("select count(*) from webhook_deliveries where id = %s", (delivery_id,)) == [(0,)]
