"""008 test support: real agents with published versions, completed live calls seeded with
transcripts, and a fake text runner that plays the voice-worker's ``textsim`` role against the
internal endpoints (spec, call events, result) the way the worker does.
"""

from __future__ import annotations

import copy
import json
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest_asyncio

from app.core.ids import new_id
from app.features import job_functions
from tests.agent_helpers import create_ok
from tests.conftest import Account
from tests.runtime_support import SERVICE_HEADERS, RecordingQueue, owner_sql

PROMPT = "You book cleaning appointments for Bright Smiles dental clinic."

BOOKING_LINES: list[tuple[str, str]] = [
    ("agent", "Hi, thanks for calling Bright Smiles. How can I help?"),
    ("user", "I'd like to book a cleaning, Tuesday if possible."),
    ("agent", "I have Tuesday at 10 in the morning. Shall I book it?"),
    ("user", "Yes please."),
    ("agent", "Booked for Tuesday at 10. Anything else?"),
    ("user", "No, thanks a lot."),
    ("agent", "Have a good day."),
]


@dataclass
class SimAgent:
    agent_id: str
    version_id: str
    body: dict[str, Any]


async def publish(client: httpx.AsyncClient, account: Account, agent_id: str, version_id: str) -> None:
    response = await client.put(
        f"/v1/agents/{agent_id}/published-version", json={"version_id": version_id}, headers=account.headers
    )
    assert response.status_code == 200, response.text


async def make_agent(
    client: httpx.AsyncClient,
    account: Account,
    *,
    prompt: str = PROMPT,
    published: bool = True,
    name: str | None = None,
    **config: Any,
) -> SimAgent:
    body = await create_ok(
        client,
        account,
        name=name or f"Clinic {new_id('agt')[-5:]}",
        config={"prompt": prompt, **config},
    )
    version_id = str(body["draft_version"]["id"])
    if published:
        await publish(client, account, body["id"], version_id)
    return SimAgent(body["id"], version_id, body)


def transcript_items(lines: Sequence[tuple[str, str]], tools: Sequence[Mapping[str, Any]] = ()) -> list[Any]:
    """Message items in the 003 transcript shape; ``tools`` entries ``{after, name, output,
    arguments?}`` add a tool call and its result after line ``after``."""
    items: list[dict[str, Any]] = []
    turn = 0
    for index, (role, text) in enumerate(lines):
        item: dict[str, Any] = {"type": "message", "role": role, "text": text}
        if role == "agent":
            item["turn_index"] = turn
            turn += 1
        items.append(item)
        for n, tool in enumerate(t for t in tools if t["after"] == index):
            ref = f"ref{index}_{n}"
            items.append(
                {
                    "type": "tool_call",
                    "name": tool["name"],
                    "ref": ref,
                    "arguments": tool.get("arguments", {}),
                }
            )
            items.append({"type": "tool_result", "name": tool["name"], "ref": ref, "output": tool["output"]})
    return items


def seed_live_call(
    workspace_id: str,
    agent: SimAgent | tuple[str, str],
    *,
    lines: Sequence[tuple[str, str]] = BOOKING_LINES,
    tools: Sequence[Mapping[str, Any]] = (),
    origin: str = "live",
    status: str = "completed",
    transcript: bool = True,
    ended_ago: timedelta = timedelta(hours=1),
    channel: str = "web",
    variables: Mapping[str, str] | None = None,
    node_path: Sequence[str] = (),
) -> str:
    """A completed call row with a finalised transcript (owner SQL, no pipeline)."""
    agent_id, version_id = (agent.agent_id, agent.version_id) if isinstance(agent, SimAgent) else agent
    call_id = new_id("call")
    ended = datetime.now(UTC) - ended_ago
    items = transcript_items(lines, tools)
    for i, node in enumerate(node_path):
        items.append(
            {"type": "flow_transition", "from_node_id": node_path[i - 1] if i else None, "to_node_id": node}
        )
    owner_sql(
        "insert into calls (id, workspace_id, agent_id, agent_version_id, origin, channel, direction, "
        "status, "
        "created_at, connected_at, ended_at, completed_at, billable_seconds, sentiment, pipeline_status, "
        "transcript, dynamic_variables, disconnect_reason, simulation_run_id) "
        "values (%s, %s, %s, %s, %s, %s, 'inbound', %s, %s, %s, %s, %s, 60, 'neutral', 'done', %s::jsonb, "
        "%s::jsonb, 'user_hangup', %s)",
        (
            call_id,
            workspace_id,
            agent_id,
            version_id,
            origin,
            channel,
            status,
            ended - timedelta(seconds=63),
            ended - timedelta(seconds=60),
            ended,
            ended if status == "completed" else None,
            json.dumps({"items": items}) if transcript else None,
            json.dumps(dict(variables or {"customer_name": "Priya"})),
            new_id("srun") if origin == "simulation" else None,
        ),
    )
    return call_id


@dataclass
class RunnerResult:
    spec: dict[str, Any]
    events: list[dict[str, Any]] = field(default_factory=list)


class FakeTextRunner:
    """Plays the textsim worker: GET spec, POST events to the output call, POST result."""

    def __init__(self, client: httpx.AsyncClient) -> None:
        self.client = client
        self.calls: list[tuple[str, str]] = []

    async def single_turn(
        self,
        test_run_id: str,
        test_case_id: str,
        *,
        reply: str | None = None,
        status: str = "completed",
        tool_calls: Sequence[Mapping[str, Any]] = (),
        nodes_visited: Sequence[str] = (),
        error_message: str | None = None,
    ) -> dict[str, Any] | None:
        base = f"/v1/internal/test-runs/{test_run_id}/cases/{test_case_id}"
        spec = await self.client.get(f"{base}/spec", headers=SERVICE_HEADERS)
        if spec.status_code in (404, 409):
            return None
        assert spec.status_code == 200, spec.text
        body = spec.json()
        answer = reply if reply is not None else f"I can help with that. You said: {body['user_prompt'][:60]}"
        result = await self.client.post(
            f"{base}/result",
            json={
                "status": status,
                "agent_response": answer if status == "completed" else None,
                "tool_calls": list(tool_calls),
                "nodes_visited": list(nodes_visited),
                "usage": {
                    "agent": {"model": "azure_openai/gpt-5.1", "input_tokens": 400, "output_tokens": 40}
                },
                "duration_ms": 850,
                "error_message": error_message,
            },
            headers=SERVICE_HEADERS,
        )
        assert result.status_code == 204, result.text
        self.calls.append(("single_turn", test_case_id))
        body = dict(body)
        return body

    async def simulation(
        self,
        simulation_run_id: str,
        *,
        replies: Sequence[str] | None = None,
        end_reason: str | None = None,
        fail: str | None = None,
        tool: Mapping[str, Any] | None = None,
        node_path: Sequence[str] = (),
        diverged_at_turn: int | None = None,
    ) -> RunnerResult | None:
        """Run one simulation: replay sends the recorded caller turns, persona a short scripted
        conversation; the agent answers with ``replies`` (cycled) or a stock line."""
        base = f"/v1/internal/simulation-runs/{simulation_run_id}"
        got = await self.client.get(f"{base}/spec", headers=SERVICE_HEADERS)
        if got.status_code in (404, 409):
            return None
        assert got.status_code == 200, got.text
        spec = got.json()
        out = RunnerResult(spec)
        call_id = spec["output_call_id"]
        now = datetime.now(UTC)
        seq = 0

        def event(type_: str, **body: Any) -> dict[str, Any]:
            nonlocal seq, now
            seq += 1
            now += timedelta(seconds=2)
            return {"seq": seq, "type": type_, "occurred_at": now.isoformat(), "offset_ms": None, **body}

        events = [event("status", status="in_progress")]
        if fail:
            events.append(event("status", status="ended", disconnect_reason="error"))
            await self._post_events(call_id, events)
            await self._result(
                base, {"status": "failed", "end_reason": "error", "usage": {}, "error_message": fail}
            )
            out.events = events
            return out
        caller = (
            list(spec.get("caller_turns") or [])
            if spec["mode"] == "replay"
            else ["Hi, I need to move my cleaning."]
        )
        stock = list(replies or ["Sure, I can help with that."])
        turn = 0

        def say_agent(i: int) -> None:
            nonlocal turn
            item: dict[str, Any] = {
                "type": "message",
                "role": "agent",
                "text": stock[i % len(stock)],
                "turn_index": turn,
            }
            if node_path:
                item["node_id"] = node_path[min(i, len(node_path) - 1)]
            events.append(event("transcript_item", item=item))
            turn += 1

        if spec.get("start_speaker", "agent") == "agent":
            say_agent(0)
        for i, text in enumerate(caller):
            events.append(event("transcript_item", item={"type": "message", "role": "user", "text": text}))
            if tool is not None and i == 0:
                ref = "simref0"
                events.append(
                    event(
                        "transcript_item",
                        item={"type": "tool_call", "name": tool["name"], "ref": ref, "arguments": {}},
                    )
                )
                events.append(
                    event(
                        "transcript_item",
                        item={
                            "type": "tool_result",
                            "name": tool["name"],
                            "ref": ref,
                            "output": tool["output"],
                            "answer_source": tool["answer_source"],
                        },
                    )
                )
            say_agent(i + 1)
        for i, node in enumerate(node_path):
            events.append(
                event("flow_transition", to_node_id=node, from_node_id=node_path[i - 1] if i else None)
            )
        events.append(
            event(
                "usage",
                usage={
                    "llm": [
                        {
                            "provider": "azure_openai",
                            "model": "gpt-5.1",
                            "input_tokens": 900,
                            "output_tokens": 90,
                        }
                    ]
                },
            )
        )
        reason = end_reason or ("caller_turns_exhausted" if spec["mode"] == "replay" else "caller_hung_up")
        disconnect = {"agent_hangup": "agent_hangup", "call_transfer": "call_transfer"}.get(
            reason, "user_hangup"
        )
        events.append(event("status", status="ended", disconnect_reason=disconnect))
        await self._post_events(call_id, events)
        counts = {"mock": 0, "recorded": 0, "synthesized": 0, "error": 0}
        if tool is not None:
            counts[tool["answer_source"]] += 1
        usage: dict[str, Any] = {
            "agent": {"model": "azure_openai/gpt-5.1", "input_tokens": 900, "output_tokens": 90}
        }
        if spec["mode"] == "persona":
            usage["caller"] = {"model": "openai/gpt-5-mini", "input_tokens": 600, "output_tokens": 60}
        if tool is not None and tool["answer_source"] == "synthesized":
            usage["synth"] = {"model": "openai/gpt-5-mini", "input_tokens": 200, "output_tokens": 30}
        await self._result(
            base,
            {
                "status": "completed",
                "end_reason": reason,
                "diverged_at_turn": diverged_at_turn,
                "answer_source_counts": counts,
                "usage": usage,
                "error_message": None,
            },
        )
        out.events = events
        self.calls.append(("simulation", simulation_run_id))
        return out

    async def _post_events(self, call_id: str, events: list[dict[str, Any]]) -> None:
        response = await self.client.post(
            f"/v1/internal/calls/{call_id}/events", json={"events": events}, headers=SERVICE_HEADERS
        )
        assert response.status_code == 200, response.text

    async def _result(self, base: str, body: dict[str, Any]) -> None:
        response = await self.client.post(f"{base}/result", json=body, headers=SERVICE_HEADERS)
        assert response.status_code == 204, response.text


def snapshot_copy(config: Mapping[str, Any]) -> dict[str, Any]:
    return copy.deepcopy(dict(config))


# Job environment ------------------------------------------------------------------------------


@dataclass
class TextsimRecorder:
    """Stands in for the ``arq:textsim`` queue: records what the API dispatched."""

    jobs: list[tuple[str, tuple[Any, ...]]] = field(default_factory=list)

    async def enqueue(self, name: str, *args: Any, job_id: str | None = None) -> None:
        self.jobs.append((name, tuple(args)))


TextsimHandler = Callable[[str, tuple[Any, ...]], Awaitable[Any]]


@dataclass
class SimEnv:
    app: Any
    client: httpx.AsyncClient
    queue: Any
    textsim: TextsimRecorder
    runner: FakeTextRunner
    llm: Any

    def ctx(self) -> dict[str, Any]:
        state = self.app.state
        return {
            "db": state.db,
            "settings": state.settings,
            "jobs": self.queue,
            "redis": state.redis,
            "textsim": self.textsim,
            "adapter_catalog": state.adapter_catalog,
            "livekit": state.livekit,
            "http": None,
        }

    async def run_api_jobs(self, *, include_deferred: bool = True) -> int:
        functions = job_functions()
        ran = 0
        for _ in range(50):
            runnable = [j for j in self.queue.jobs if include_deferred or not j.defer_by_s]
            if not runnable:
                break
            for job in runnable:
                self.queue.jobs.remove(job)
                if job.name in functions:
                    await functions[job.name](self.ctx(), *job.args)
                    ran += 1
        return ran

    async def drain(self, handler: TextsimHandler | None = None, *, rounds: int = 30) -> None:
        """Run API jobs and text runner jobs until both queues are empty."""
        for _ in range(rounds):
            await self.run_api_jobs()
            if not self.textsim.jobs:
                if not self.queue.jobs:
                    return
                continue
            pending, self.textsim.jobs = self.textsim.jobs, []
            for name, args in pending:
                if handler is not None:
                    await handler(name, args)
                elif name == "run_single_turn":
                    await self.runner.single_turn(*args)
                else:
                    await self.runner.simulation(*args)


@pytest_asyncio.fixture
async def sim_env(app: Any, client: httpx.AsyncClient) -> AsyncIterator[SimEnv]:
    from app.evals import install as quality_install
    from app.llms import runtime as model_runtime
    from app.llms.adapters.base import ChatMessage
    from app.llms.adapters.fake import PURPOSE_REPLIES
    from tests.fakes.fake_llm import FakeLlm
    from tests.unit.evaluators.helpers import offline_llm

    previous = getattr(app.state, "jobs", None)
    queue = RecordingQueue()
    app.state.jobs = queue
    quality = offline_llm()

    def responder(system: str, user: str, purpose: str | None) -> str:
        if purpose in (
            "test_case_judge",
            "persona_extraction",
            "test_case_generation",
            "issue_naming",
            "issue_fix_draft",
        ):
            return PURPOSE_REPLIES[purpose]([ChatMessage("user", user)], system)
        assert quality.responder is not None
        return quality.responder(system, user, purpose)

    llm = FakeLlm(responder=responder)
    model_runtime.install(app.state.settings, llm=llm, queue=queue)
    quality_install.install_handlers()
    env = SimEnv(app, client, queue, TextsimRecorder(), FakeTextRunner(client), llm)
    yield env
    model_runtime.install(app.state.settings, queue=previous)
    quality_install.install_handlers()
    app.state.jobs = previous
