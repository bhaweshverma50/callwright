"""Voice runtime (003) test support: a fake 002 agent-versions port, an inline job queue, event
builders shaped like the worker's, and the ``runtime`` fixture that installs them.

``calls.agent_id``, ``calls.agent_version_id`` and ``call_costs.call_id`` are foreign keys since
the wave 2 integration (``s003_0002``), so the fake writes a matching ``agents`` and
``agent_versions`` row for every agent and version it hands out (``materialize``), and
``insert_call`` gives 001 tests a real call row to charge.

Loaded as a pytest plugin from ``tests/conftest.py``. Nothing here needs a media server: the app
runs with ``LIVEKIT_MODE=fake``.
"""

from __future__ import annotations

import copy
import hashlib
import json
import uuid
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import httpx
import psycopg
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing import service as billing
from app.calls import ports
from app.calls.agent_versions import AgentSnapshot
from app.core.ids import new_id
from app.core.queue import Job
from app.features import job_functions

DEFAULT_CONFIG: dict[str, Any] = {
    "schema_version": 1,
    "type": "single_prompt",
    "language": "en-US",
    "llm": {"provider": "azure_openai", "model": "gpt-5.1", "temperature": 1.0},
    "prompt": "You are a helpful agent for {{company_name}}.",
    "begin_message": "Hi {{customer_name}}, thanks for calling.",
    "start_speaker": "agent",
    "dynamic_variables": [
        {"name": "customer_name", "default": "there"},
        {"name": "company_name", "default": "Acme Bank"},
    ],
    "stt": {"provider": "deepgram", "model": None},
    "tts": {"provider": "elevenlabs", "model": "eleven_flash_v2_5", "voice_id": "voice_1"},
    "noise_cancellation": {"provider": "sanas", "model": "vi"},
    "call_behavior": {"end_on_silence_s": 30, "max_duration_s": 600, "ring_duration_ms": 5000},
    "advanced": {"webhook_url": None, "webhook_timeout_ms": 3000, "recording": "inherit"},
    "tool_ids": [],
    "kb_ids": [],
}
SERVICE_HEADERS = {"Authorization": "Bearer dev-service-token"}


def agent_config(**overrides: Any) -> dict[str, Any]:
    """``DEFAULT_CONFIG`` with top-level keys replaced and ``advanced``/``call_behavior`` merged."""
    config = copy.deepcopy(DEFAULT_CONFIG)
    for key, value in overrides.items():
        if key in ("advanced", "call_behavior") and isinstance(value, Mapping):
            config[key] = {**config[key], **value}
        else:
            config[key] = value
    return config


async def _current_workspace(session: AsyncSession) -> str:
    return str(
        (await session.execute(text("select current_setting('app.workspace_id', true)"))).scalar() or ""
    )


@dataclass
class FakeAgent:
    agent_id: str
    workspace_id: str
    agent_type: str
    draft: AgentSnapshot
    published: AgentSnapshot | None


def materialize_version(snapshot: AgentSnapshot) -> None:
    """Write ``snapshot`` (and its agent on first use) as owner, so foreign keys from ``calls``
    resolve. The agent's draft pointer stays on its first version; the fake keeps the rest."""
    config = json.dumps(dict(snapshot.config), sort_keys=True, default=str)
    digest = hashlib.sha256(config.encode()).hexdigest()
    summary = json.dumps({"llm_model": "", "tts_provider": "", "tts_voice_id": "", "tool_count": 0})
    with psycopg.connect(_owner_dsn()) as conn:
        conn.execute(
            """
            insert into agent_versions (id, workspace_id, agent_id, version_number, schema_version,
                                        config, content_hash, source, summary)
            select %s, %s, %s, coalesce(max(version_number), 0) + 1, 1, %s::jsonb, %s, 'save', %s::jsonb
              from agent_versions where agent_id = %s
            """,
            (
                snapshot.version_id,
                snapshot.workspace_id,
                snapshot.agent_id,
                config,
                digest,
                summary,
                snapshot.agent_id,
            ),
        )
        conn.execute(
            """
            insert into agents (id, workspace_id, name, type, language, draft_config, draft_version_id)
            values (%s, %s, %s, %s, %s, %s::jsonb, %s)
            on conflict (id) do nothing
            """,
            (
                snapshot.agent_id,
                snapshot.workspace_id,
                f"Test agent {snapshot.agent_id[-6:]}",
                snapshot.agent_type,
                str(snapshot.config.get("language") or "en-US"),
                config,
                snapshot.version_id,
            ),
        )


def insert_call(workspace_id: str, *, status: str = "completed") -> str:
    """A real ``calls`` row (with its agent and version) for tests that need a call id, such as
    001's ``charge_call`` tests now that ``call_costs.call_id`` references ``calls``."""
    snapshot = AgentSnapshot(new_id("agv"), new_id("agt"), workspace_id, "single_prompt", agent_config())
    materialize_version(snapshot)
    call_id = new_id("call")
    owner_sql(
        """
        insert into calls (id, workspace_id, agent_id, agent_version_id, channel, direction, status)
        values (%s, %s, %s, %s, 'web', 'inbound', %s)
        """,
        (call_id, workspace_id, snapshot.agent_id, snapshot.version_id, status),
    )
    return call_id


@dataclass
class FakeAgentVersions:
    """In-memory stand-in for ``calls.agent_versions`` (RLS emulated by workspace).

    With ``materialize`` (the ``runtime`` fixture) every version is also written to the database so
    the call foreign keys hold; the port answers stay in memory.
    """

    agents: dict[str, FakeAgent] = field(default_factory=dict)
    versions: dict[str, AgentSnapshot] = field(default_factory=dict)
    snapshot_calls: int = 0
    materialize: bool = False

    def add_agent(
        self,
        workspace_id: str,
        config: Mapping[str, Any] | None = None,
        *,
        agent_type: str = "single_prompt",
        published: bool = True,
    ) -> FakeAgent:
        agent_id = new_id("agt")
        snapshot = self._version(agent_id, workspace_id, agent_type, config or agent_config())
        agent = FakeAgent(agent_id, workspace_id, agent_type, snapshot, snapshot if published else None)
        self.agents[agent_id] = agent
        return agent

    def save_draft(self, agent_id: str, config: Mapping[str, Any]) -> AgentSnapshot:
        agent = self.agents[agent_id]
        agent.draft = self._version(agent_id, agent.workspace_id, agent.agent_type, config)
        return agent.draft

    def publish(self, agent_id: str) -> AgentSnapshot:
        agent = self.agents[agent_id]
        agent.published = agent.draft
        return agent.draft

    def _version(
        self, agent_id: str, workspace_id: str, agent_type: str, config: Mapping[str, Any]
    ) -> AgentSnapshot:
        snapshot = AgentSnapshot(
            new_id("agv"), agent_id, workspace_id, agent_type, copy.deepcopy(dict(config))
        )
        self.versions[snapshot.version_id] = snapshot
        if self.materialize:
            materialize_version(snapshot)
        return snapshot

    async def _visible(self, session: AsyncSession, agent_id: str) -> FakeAgent | None:
        agent = self.agents.get(agent_id)
        if agent is None or agent.workspace_id != await _current_workspace(session):
            return None
        return agent

    async def agent_exists(self, session: AsyncSession, agent_id: str) -> bool:
        return await self._visible(session, agent_id) is not None

    async def get_snapshot(self, session: AsyncSession, version_id: str) -> AgentSnapshot | None:
        snapshot = self.versions.get(version_id)
        if snapshot is None or snapshot.workspace_id != await _current_workspace(session):
            return None
        return snapshot

    async def snapshot_for_test(self, session: AsyncSession, agent_id: str) -> AgentSnapshot | None:
        self.snapshot_calls += 1
        agent = await self._visible(session, agent_id)
        return agent.draft if agent else None

    async def get_published(self, session: AsyncSession, agent_id: str) -> AgentSnapshot | None:
        agent = await self._visible(session, agent_id)
        return agent.published if agent else None


@dataclass
class RecordingQueue:
    """``JobQueue`` that records jobs; tests run them inline with ``run``."""

    jobs: list[Job] = field(default_factory=list)
    history: list[Job] = field(default_factory=list)

    async def enqueue(
        self, name: str, *args: Any, defer_by_s: float | None = None, job_id: str | None = None
    ) -> None:
        job = Job(name, tuple(args), defer_by_s, job_id)
        self.jobs.append(job)
        self.history.append(job)

    def names(self) -> list[str]:
        return [j.name for j in self.jobs]

    def clear(self) -> None:
        self.jobs.clear()

    async def run(
        self,
        ctx: dict[str, Any],
        *,
        names: tuple[str, ...] | None = None,
        include_deferred: bool = False,
        max_rounds: int = 20,
    ) -> list[tuple[Job, Any]]:
        """Run queued jobs (and the jobs they enqueue) until none match. Returns (job, result)."""
        functions = job_functions()
        done: list[tuple[Job, Any]] = []
        for _ in range(max_rounds):
            runnable = [
                j
                for j in self.jobs
                if (names is None or j.name in names) and (include_deferred or not j.defer_by_s)
            ]
            if not runnable:
                break
            for job in runnable:
                self.jobs.remove(job)
                done.append((job, await functions[job.name](ctx, *job.args)))
        return done


class Events:
    """Event builder with the worker's shapes (``worker/metrics.py`` ``EventRecorder``)."""

    def __init__(self, start: datetime | None = None) -> None:
        self.seq = 0
        self.clock = start or datetime.now(UTC)

    def _emit(self, type_: str, body: dict[str, Any], *, at: datetime | None = None) -> dict[str, Any]:
        self.seq += 1
        return {
            "seq": self.seq,
            "type": type_,
            "occurred_at": (at or self.clock).isoformat(),
            "offset_ms": None,
            **body,
        }

    def advance(self, seconds: float) -> None:
        self.clock += timedelta(seconds=seconds)

    def status(self, status: str, **body: Any) -> dict[str, Any]:
        return self._emit("status", {"status": status, **body})

    def turn(self, index: int, e2e_ms: int | None = 700, **body: Any) -> dict[str, Any]:
        base = {
            "turn_index": index,
            "stt_final_ms": 150,
            "eou_delay_ms": 300,
            "llm_ttft_ms": 250,
            "tts_ttfb_ms": 120,
            "e2e_ms": e2e_ms,
            "tool_ms": None,
            "interrupted": False,
        }
        return self._emit("turn", {**base, **body})

    def message(self, role: str, text_: str, **item: Any) -> dict[str, Any]:
        return self._emit(
            "transcript_item", {"item": {"type": "message", "role": role, "text": text_, **item}}
        )

    def usage(
        self,
        *,
        audio_ms: int = 60000,
        input_tokens: int = 1000,
        output_tokens: int = 50,
        chars: int = 300,
        stt_model: str = "nova-3",
    ) -> dict[str, Any]:
        return self._emit(
            "usage",
            {
                "usage": {
                    "stt": [{"provider": "deepgram", "model": stt_model, "audio_ms": audio_ms}],
                    "llm": [
                        {
                            "provider": "azure_openai",
                            "model": "gpt-5.1",
                            "input_tokens": input_tokens,
                            "cached_input_tokens": 0,
                            "output_tokens": output_tokens,
                        }
                    ],
                    "tts": [{"provider": "elevenlabs", "model": "eleven_flash_v2_5", "characters": chars}],
                    "nc": [{"provider": "sanas", "model": "vi", "audio_ms": audio_ms}],
                }
            },
        )


@dataclass
class Runtime:
    app: FastAPI
    versions: FakeAgentVersions
    queue: RecordingQueue
    http: httpx.AsyncClient

    @property
    def db(self) -> Any:
        return self.app.state.db

    @property
    def livekit(self) -> Any:
        return self.app.state.livekit

    @property
    def catalog(self) -> Any:
        return self.app.state.adapter_catalog

    def ctx(self, http: httpx.AsyncClient | None = None) -> dict[str, Any]:
        return {
            "db": self.app.state.db,
            "settings": self.app.state.settings,
            "livekit": self.app.state.livekit,
            "jobs": self.queue,
            "adapter_catalog": self.app.state.adapter_catalog,
            "http": http or self.http,
        }

    async def run_jobs(self, *names: str, http: httpx.AsyncClient | None = None) -> list[tuple[Job, Any]]:
        return await self.queue.run(self.ctx(http), names=names or None)

    async def workspace(self, *, trial: bool = True, concurrency: int | None = None) -> tuple[str, str]:
        from tests.conftest import make_workspace

        user_id, ws = await make_workspace(self.app, trial=trial)
        if concurrency is not None:
            set_concurrency(ws, concurrency)
        return user_id, ws

    async def set_balance(self, workspace_id: str, target: Decimal) -> None:
        async with self.db.transaction(workspace_id=workspace_id) as session:
            balance = await billing.get_balance(session, workspace_id)
            delta = (target - balance).quantize(Decimal("0.000001"))
            if delta != 0:
                await billing.post_transaction(
                    session,
                    workspace_id=workspace_id,
                    type="adjustment",
                    amount_usd=delta,
                    description="test",
                )


def _owner_dsn() -> str:
    from tests.conftest import PG, TEST_DB

    return f"postgresql://callwright:callwright@{PG}/{TEST_DB}"


def set_concurrency(workspace_id: str, limit: int) -> None:
    with psycopg.connect(_owner_dsn(), autocommit=True) as conn:
        conn.execute("update workspaces set concurrency_limit = %s where id = %s", (limit, workspace_id))


def owner_sql(sql: str, params: tuple[Any, ...] = ()) -> list[tuple[Any, ...]]:
    """Run SQL as the owner (bypasses RLS): back-dating timestamps, checking raw rows."""
    with psycopg.connect(_owner_dsn(), autocommit=True) as conn:
        cur = conn.execute(sql, params)
        return list(cur.fetchall()) if cur.description else []


def idem() -> dict[str, str]:
    return {"Idempotency-Key": f"test-{uuid.uuid4().hex}"}


async def start_web_call(
    client: httpx.AsyncClient, headers: Mapping[str, str], agent_id: str, **body: Any
) -> httpx.Response:
    return await client.post(
        "/v1/sessions/web-call", json={"agent_id": agent_id, **body}, headers={**headers, **idem()}
    )


@dataclass
class CallSetup:
    workspace_id: str
    call_id: str
    agent: FakeAgent
    events: Events


async def post_events(runtime: Runtime, call_id: str, events: list[dict[str, Any]]) -> Any:
    from callwright_contract.protocol import EventBatch

    from app.call_events.service import ingest
    from app.core.queue import dispatch

    settings = runtime.app.state.settings
    out = await ingest(
        runtime.db,
        call_id,
        EventBatch.model_validate({"events": events}),
        catalog=runtime.catalog,
        grace_usd=settings.credit_grace_usd,
    )
    await dispatch(runtime.queue, out.deferred)
    return out.result


async def admitted_call(
    runtime: Runtime,
    workspace_id: str | None = None,
    *,
    config: Mapping[str, Any] | None = None,
    origin: str = "test",
    room: bool = True,
) -> CallSetup:
    from sqlalchemy import update

    from app.calls import service as calls
    from app.calls.models import Call

    ws = workspace_id or (await runtime.workspace())[1]
    agent = runtime.versions.add_agent(ws, config)
    admission = await calls.admit(
        runtime.db,
        calls.AdmissionRequest(ws, agent.agent_id, "web", "inbound", version="draft", origin=origin),
        catalog=runtime.catalog,
    )
    assert admission.admitted, admission.refusal
    if room:
        async with runtime.db.transaction(workspace_id=ws) as session:
            await session.execute(
                update(Call).where(Call.id == admission.call.id).values(room_name=f"call-{admission.call.id}")
            )
    started = datetime.now(UTC) - timedelta(minutes=5)
    return CallSetup(ws, admission.call.id, agent, Events(started))


async def ended_call(
    runtime: Runtime,
    workspace_id: str | None = None,
    *,
    config: Mapping[str, Any] | None = None,
    seconds: float = 30.0,
    turns: int = 3,
    origin: str = "test",
    reason: str = "user_hangup",
) -> CallSetup:
    """An admitted call that connected, exchanged ``turns`` replies and ended ``seconds`` later."""
    setup = await admitted_call(runtime, workspace_id, config=config, origin=origin)
    ev = setup.events
    batch = [ev.status("in_progress"), ev.turn(0, e2e_ms=900), ev.message("agent", "Hi there")]
    for i in range(1, turns + 1):
        batch += [
            ev.message("user", f"question {i}"),
            ev.turn(i, e2e_ms=600 + 50 * i),
            ev.message("agent", f"a{i}"),
        ]
    batch.append(ev.usage())
    ev.advance(seconds)
    batch.append(ev.status("ended", disconnect_reason=reason))
    await post_events(runtime, setup.call_id, batch)
    return setup


def dispatch_metadata(runtime: Runtime, call_id: str) -> dict[str, Any]:
    """The metadata the API dispatched the worker with for ``call_id`` (fake media server)."""
    for _room, _agent, metadata in reversed(runtime.livekit.dispatches):
        if metadata.get("call_id") == call_id:
            return dict(metadata)
    raise AssertionError(f"no dispatch for {call_id}")


@pytest_asyncio.fixture
async def runtime(app: FastAPI) -> AsyncIterator[Runtime]:
    previous_port = ports.registry.agent_versions
    previous_jobs = getattr(app.state, "jobs", None)
    versions = FakeAgentVersions(materialize=True)
    queue = RecordingQueue()
    ports.registry.agent_versions = versions
    app.state.jobs = queue
    async with httpx.AsyncClient() as http:
        yield Runtime(app, versions, queue, http)
    ports.registry.agent_versions = previous_port
    app.state.jobs = previous_jobs
