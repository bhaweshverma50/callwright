"""007 test support: the quality runtime with an offline judge, scripted calls that run the real
post-call pipeline, and owner-SQL seeding of runs and labels for review and calibration.

``quality`` installs the 007 pipeline handlers and a ``FakeLlm`` that answers like the offline
fake adapter (or as a test scripts it), and restores the handlers afterwards (003's pipeline
runner tests clear them).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
import pytest_asyncio
from fastapi import FastAPI

from app.core.ids import new_id
from app.evals import install as quality_install
from app.evaluators.registry import builtin_id
from app.llms import runtime as model_runtime
from tests.fakes.fake_llm import FakeLlm
from tests.runtime_support import Runtime, _owner_dsn, admitted_call, agent_config, owner_sql, post_events
from tests.unit.evaluators.helpers import offline_llm


@pytest_asyncio.fixture
async def quality(app: FastAPI) -> AsyncIterator[FakeLlm]:
    llm = offline_llm()
    model_runtime.install(app.state.settings, llm=llm, queue=getattr(app.state, "jobs", None))
    quality_install.install_handlers()
    yield llm
    model_runtime.install(app.state.settings, queue=getattr(app.state, "jobs", None))
    quality_install.install_handlers()


BOOKING = [
    ("agent", "Hi, thanks for calling Bright Smiles. How can I help?"),
    ("user", "I'd like to book a cleaning appointment, Tuesday if possible."),
    ("agent", "I have Tuesday at 10 in the morning. Shall I book it?"),
    ("user", "Yes please, thanks a lot."),
    ("agent", "Booked for Tuesday at 10. Anything else I can help with?"),
]


@dataclass
class Scripted:
    workspace_id: str
    call_id: str
    agent_id: str


async def scripted_call(
    runtime: Runtime,
    workspace_id: str | None = None,
    *,
    lines: Sequence[tuple[str, str]] = BOOKING,
    config: dict[str, Any] | None = None,
    origin: str = "live",
    latencies: Sequence[int] | None = None,
    prepare: Callable[[str, str], Awaitable[None]] | None = None,
    run_jobs: bool = True,
) -> Scripted:
    """A connected call with ``lines`` spoken, ended, and its post-call pipeline (and evaluation
    job) run. ``prepare(workspace_id, agent_id)`` runs before the pipeline (variables, settings)."""
    setup = await admitted_call(runtime, workspace_id, config=config or agent_config(), origin=origin)
    ev = setup.events
    batch = [ev.status("in_progress")]
    agent_turn = 0
    lat = list(latencies or [])
    for role, text in lines:
        if role == "agent":
            e2e = lat[agent_turn - 1] if 0 < agent_turn <= len(lat) else 700
            batch.append(ev.turn(agent_turn, e2e_ms=e2e))
            batch.append(ev.message("agent", text, turn_index=agent_turn))
            agent_turn += 1
        else:
            batch.append(ev.message("user", text))
        ev.advance(4)
    batch.append(ev.usage())
    batch.append(ev.status("ended", disconnect_reason="user_hangup"))
    await post_events(runtime, setup.call_id, batch)
    if prepare is not None:
        await prepare(setup.workspace_id, setup.agent.agent_id)
    if run_jobs:
        await runtime.run_jobs("run_pipeline")
        await runtime.run_jobs("evaluate_call")
    row = owner_sql("select agent_id from calls where id = %s", (setup.call_id,))
    return Scripted(setup.workspace_id, setup.call_id, row[0][0])


def seed_agent(workspace_id: str, agent_type: str = "single_prompt") -> tuple[str, str]:
    agent_id, version_id = new_id("agt"), new_id("agv")
    config = json.dumps({**agent_config(), "type": agent_type})
    with psycopg.connect(_owner_dsn()) as conn:
        with conn.transaction():
            conn.execute("SET CONSTRAINTS ALL DEFERRED")
            conn.execute(
                "insert into agent_versions (id, workspace_id, agent_id, version_number, schema_version, "
                "config, content_hash, source, summary) "
                "values (%s, %s, %s, 1, 1, %s::jsonb, %s, 'save', '{}'::jsonb)",
                (version_id, workspace_id, agent_id, config, hashlib.sha256(config.encode()).hexdigest()),
            )
            conn.execute(
                "insert into agents (id, workspace_id, name, type, language, draft_config, draft_version_id) "
                "values (%s, %s, %s, %s, 'en-US', %s::jsonb, %s)",
                (agent_id, workspace_id, f"Seed agent {agent_id[-4:]}", agent_type, config, version_id),
            )
    return agent_id, version_id


def seed_call(
    workspace_id: str,
    agent: tuple[str, str],
    *,
    origin: str = "live",
    ended_ago: timedelta = timedelta(hours=1),
    seconds: int = 60,
    sentiment: str | None = "neutral",
) -> str:
    call_id = new_id("call")
    ended = datetime.now(UTC) - ended_ago
    owner_sql(
        "insert into calls (id, workspace_id, agent_id, agent_version_id, origin, channel, direction, "
        "status, created_at, connected_at, ended_at, completed_at, billable_seconds, sentiment, "
        "pipeline_status, transcript) values (%s, %s, %s, %s, %s, 'web', 'inbound', 'completed', "
        "%s, %s, %s, %s, %s, %s, 'done', %s::jsonb)",
        (
            call_id,
            workspace_id,
            agent[0],
            agent[1],
            origin,
            ended - timedelta(seconds=seconds + 3),
            ended - timedelta(seconds=seconds),
            ended,
            ended,
            seconds,
            sentiment,
            json.dumps({"items": [{"type": "message", "role": "agent", "text": "Hi"}]}),
        ),
    )
    return call_id


def seed_run(
    workspace_id: str,
    call_id: str,
    agent_id: str,
    evaluator: str,
    verdict: str,
    *,
    score: float | None = None,
    version: int = 1,
    status: str = "completed",
    group: str | None = None,
    items: Sequence[dict[str, Any]] = (),
) -> str:
    evl = builtin_id(evaluator) if not evaluator.startswith("evl_") else evaluator
    group = group or f"erg_seed{new_id('evr')[4:]}"
    owner_sql(
        "insert into evaluator_run_groups (run_group_id, workspace_id, call_id, trigger, "
        "idempotency_key, status) values (%s, %s, %s, 'pipeline', %s, 'done') on conflict do nothing",
        (group, workspace_id, call_id, group),
    )
    run_id = new_id("evr")
    owner_sql(
        "insert into evaluator_runs (id, workspace_id, call_id, agent_id, evaluator_id, evaluator_version, "
        "run_group_id, trigger, settings_hash, status, verdict, score, rationale, completed_at) "
        "values (%s, %s, %s, %s, %s, %s, %s, 'pipeline', 'h', %s, %s, %s, %s, now())",
        (
            run_id,
            workspace_id,
            call_id,
            agent_id,
            evl,
            version,
            group,
            status,
            verdict if status == "completed" else None,
            score if score is not None else (1.0 if verdict == "pass" else 0.0),
            "seeded" if status == "completed" else None,
        ),
    )
    for position, item in enumerate(items):
        owner_sql(
            "insert into evaluator_result_items (workspace_id, run_id, position, flow_node_id, "
            "flow_node_label, verdict, score, rationale) values (%s, %s, %s, %s, %s, %s, %s, 'seeded')",
            (
                workspace_id,
                run_id,
                position,
                item["node"],
                item.get("label"),
                item["verdict"],
                item.get("score"),
            ),
        )
    return run_id


def seed_label(workspace_id: str, call_id: str, user_id: str, label: str) -> None:
    owner_sql(
        "insert into annotations (id, workspace_id, call_id, user_id, user_display_name, label) "
        "values (%s, %s, %s, %s, 'seed', %s)",
        (new_id("ann"), workspace_id, call_id, user_id, label),
    )


def user_id() -> str:
    return new_id("usr")
