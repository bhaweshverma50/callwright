"""Post-call step runner (003 T074): fixed order, blocking steps stop the chain, non-blocking
failures are recorded, unregistered handlers are skipped, simulations skip pricing and webhook."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.calls import pipeline
from tests.runtime_support import Runtime, agent_config, ended_call, owner_sql


@pytest.fixture(autouse=True)
def _clear_handlers() -> Any:
    yield
    pipeline.register_step_handler("analyze", None)
    pipeline.register_step_handler("evaluate", None)


async def _run(runtime: Runtime, ws: str, call_id: str, **kw: Any) -> pipeline.PipelineRun:
    return await pipeline.run(runtime.db, ws, call_id, catalog=runtime.catalog, **kw)


def steps(call_id: str) -> dict[str, tuple[str, int]]:
    rows = owner_sql("select step, status, attempts from call_pipeline_steps where call_id = %s", (call_id,))
    return {r[0]: (r[1], r[2]) for r in rows}


def test_fixed_order_and_blocking_flags() -> None:
    assert pipeline.STEP_NAMES == (
        "finalize_transcript",
        "price_and_charge",
        "analyze",
        "evaluate",
        "notify_analyzed",
        "complete",
    )
    assert [s.name for s in pipeline.STEPS if s.blocking] == [
        "finalize_transcript",
        "price_and_charge",
        "complete",
    ]
    with pytest.raises(ValueError):
        pipeline.register_step_handler("price_and_charge", lambda c, s: None)  # type: ignore[arg-type,return-value]


async def test_registered_handlers_run_in_order(runtime: Runtime) -> None:
    seen: list[str] = []

    async def analyze(call_id: str, session: AsyncSession) -> None:
        seen.append("analyze")

    async def evaluate(call_id: str, session: AsyncSession) -> None:
        seen.append("evaluate")

    pipeline.register_step_handler("analyze", analyze)
    pipeline.register_step_handler("evaluate", evaluate)
    setup = await ended_call(runtime)
    result = await _run(runtime, setup.workspace_id, setup.call_id)
    assert result.status == "finished" and seen == ["analyze", "evaluate"]
    assert list(result.steps) == list(pipeline.STEP_NAMES)
    assert steps(setup.call_id)["analyze"] == ("done", 1)


async def test_unregistered_handlers_are_skipped(runtime: Runtime) -> None:
    setup = await ended_call(runtime)
    await _run(runtime, setup.workspace_id, setup.call_id)
    assert (
        steps(setup.call_id)["analyze"][0] == "skipped" and steps(setup.call_id)["evaluate"][0] == "skipped"
    )


async def test_non_blocking_failure_is_a_warning(runtime: Runtime) -> None:
    async def broken(call_id: str, session: AsyncSession) -> None:
        raise RuntimeError("model unavailable")

    pipeline.register_step_handler("analyze", broken)
    setup = await ended_call(
        runtime, config=agent_config(advanced={"webhook_url": "https://hooks.example.com/x"})
    )
    result = await _run(runtime, setup.workspace_id, setup.call_id)
    assert result.status == "finished"
    assert steps(setup.call_id)["analyze"] == ("failed", 1)
    rows = owner_sql(
        "select status, pipeline_status, pipeline_warnings from calls where id = %s", (setup.call_id,)
    )
    assert rows == [("completed", "done_with_warnings", ["analyze"])]
    # Still charged and notified (US4.3), with the failed step listed.
    assert owner_sql("select count(*) from credit_transactions where call_id = %s", (setup.call_id,)) == [
        (1,)
    ]
    body = owner_sql(
        "select body::jsonb->'call'->'processing_warnings' from webhook_deliveries "
        "where call_id = %s and event = 'call_analyzed'",
        (setup.call_id,),
    )
    assert body == [(["analyze"],)]


async def test_blocking_failure_stops_the_chain_and_retries(
    runtime: Runtime, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = 0
    original = pipeline.HANDLERS["price_and_charge"]

    async def flaky(ctx: pipeline.StepContext) -> pipeline.Outcome:
        nonlocal calls
        calls += 1
        if calls < 3:
            raise ConnectionError("ledger unavailable")
        return await original(ctx)

    monkeypatch.setitem(pipeline.HANDLERS, "price_and_charge", flaky)
    setup = await ended_call(runtime)
    first = await _run(runtime, setup.workspace_id, setup.call_id)
    assert first.status == "retry" and first.retry_in_s == pipeline.RETRY_BASE_S
    state = steps(setup.call_id)
    assert state["finalize_transcript"] == ("done", 1)
    assert state["price_and_charge"] == ("pending", 1)
    assert state["analyze"] == ("pending", 0) and state["complete"] == ("pending", 0)
    assert owner_sql("select status from calls where id = %s", (setup.call_id,)) == [("processing",)]
    second = await _run(runtime, setup.workspace_id, setup.call_id)
    assert second.status == "retry" and second.retry_in_s == pipeline.RETRY_BASE_S * 2
    third = await _run(runtime, setup.workspace_id, setup.call_id)
    assert third.status == "finished"
    assert steps(setup.call_id)["price_and_charge"] == ("done", 3)
    assert owner_sql("select count(*) from credit_transactions where call_id = %s", (setup.call_id,)) == [
        (1,)
    ]


async def test_blocked_after_max_attempts(runtime: Runtime, monkeypatch: pytest.MonkeyPatch) -> None:
    async def always(ctx: pipeline.StepContext) -> pipeline.Outcome:
        raise ConnectionError("down")

    monkeypatch.setitem(pipeline.HANDLERS, "finalize_transcript", always)
    setup = await ended_call(runtime)
    for _ in range(pipeline.MAX_BLOCKING_ATTEMPTS - 1):
        assert (await _run(runtime, setup.workspace_id, setup.call_id)).status == "retry"
    final = await _run(runtime, setup.workspace_id, setup.call_id)
    assert final.status == "blocked"
    assert owner_sql("select pipeline_status from calls where id = %s", (setup.call_id,)) == [("blocked",)]
    assert steps(setup.call_id)["price_and_charge"] == ("pending", 0)


async def test_simulation_skips_pricing_and_webhook(runtime: Runtime) -> None:
    setup = await ended_call(
        runtime,
        origin="simulation",
        config=agent_config(advanced={"webhook_url": "https://hooks.example.com/x"}),
    )
    await _run(runtime, setup.workspace_id, setup.call_id)
    state = steps(setup.call_id)
    assert state["price_and_charge"][0] == "skipped" and state["notify_analyzed"][0] == "skipped"
    assert owner_sql("select count(*) from credit_transactions where call_id = %s", (setup.call_id,)) == [
        (0,)
    ]
    events = owner_sql("select event from webhook_deliveries where call_id = %s", (setup.call_id,))
    assert ("call_analyzed",) not in events


async def test_voicemail_ends_as_voicemail(runtime: Runtime) -> None:
    setup = await ended_call(runtime, reason="voicemail_reached")
    await _run(runtime, setup.workspace_id, setup.call_id)
    assert owner_sql("select status from calls where id = %s", (setup.call_id,)) == [("voicemail",)]


async def test_never_connected_calls_never_enter_the_pipeline(runtime: Runtime) -> None:
    from tests.runtime_support import admitted_call, post_events

    setup = await admitted_call(runtime)
    await post_events(
        runtime, setup.call_id, [setup.events.status("failed", diagnostic="caller_never_joined")]
    )
    result = await _run(runtime, setup.workspace_id, setup.call_id)
    assert result.status == "not_ready" and steps(setup.call_id) == {}
    assert owner_sql("select count(*) from credit_transactions where call_id = %s", (setup.call_id,)) == [
        (0,)
    ]


async def test_transcript_and_latency_stats(runtime: Runtime) -> None:
    setup = await ended_call(runtime, turns=4)
    await _run(runtime, setup.workspace_id, setup.call_id)
    stats = owner_sql(
        "select latency_stats, transcript->'items'->1 from calls where id = %s", (setup.call_id,)
    )[0]
    latency, second_item = stats
    assert latency["turns"] == 4 and latency["greeting_ms"] == 900
    assert latency["e2e_p50_ms"] == 750 and latency["e2e_max_ms"] == 800 and latency["e2e_avg_ms"] == 725
    assert latency["llm_ttft_avg_ms"] == 250
    assert second_item == {"type": "message", "role": "user", "text": "question 1"}
