"""009 test support: a published agent with enabled checks, live calls with seeded failing
verdicts (custom reasons), the issues job runner and stubbed 008 batch completion.

``IssueEnv.detect`` posts a detection and runs the queued job; ``complete_batch`` finishes a
validation batch the way 008 and 007 would (simulated calls with verdicts per base call), so the
keep rule can be driven with exact numbers.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest_asyncio
from fastapi import FastAPI

from app.core.ids import new_id
from app.evaluators.registry import builtin_id
from tests.conftest import Account, signup
from tests.runtime_support import RecordingQueue, owner_sql
from tests.sim_support import BOOKING_LINES, SimAgent, make_agent, seed_live_call

FACT = builtin_id("factual_consistency")
TOOLS = builtin_id("tool_call_correctness")
PRICE_REASON = "The agent quoted a cleaning price of 80 dollars that is not in the price list."
OTHER_REASON = "The caller asked about parking and the agent described a garage that does not exist."


def enable(workspace_id: str, agent_id: str, *evaluators: str, enabled: bool = True) -> None:
    for evaluator in evaluators:
        owner_sql(
            "insert into agent_eval_settings (agent_id, evaluator_id, workspace_id, enabled, overrides, "
            "is_headline) values (%s, %s, %s, %s, '{}'::jsonb, false) on conflict (agent_id, evaluator_id) "
            "do update set enabled = excluded.enabled",
            (agent_id, evaluator, workspace_id, enabled),
        )


def seed_verdict(
    workspace_id: str,
    call_id: str,
    agent_id: str,
    evaluator: str,
    verdict: str,
    *,
    rationale: str = "fine",
    version: int = 1,
    items: Sequence[Mapping[str, Any]] = (),
) -> str:
    group = f"erg_{uuid.uuid4().hex[:20]}"
    owner_sql(
        "insert into evaluator_run_groups (run_group_id, workspace_id, call_id, trigger, idempotency_key, "
        "status) values (%s, %s, %s, 'pipeline', %s, 'done')",
        (group, workspace_id, call_id, group),
    )
    run_id = new_id("evr")
    owner_sql(
        "insert into evaluator_runs (id, workspace_id, call_id, agent_id, evaluator_id, evaluator_version, "
        "run_group_id, trigger, settings_hash, status, verdict, score, rationale, completed_at) "
        "values (%s, %s, %s, %s, %s, %s, %s, 'pipeline', 'h', 'completed', %s, %s, %s, now())",
        (
            run_id,
            workspace_id,
            call_id,
            agent_id,
            evaluator,
            version,
            group,
            verdict,
            1.0 if verdict == "pass" else 0.0,
            rationale,
        ),
    )
    for position, item in enumerate(items):
        owner_sql(
            "insert into evaluator_result_items (workspace_id, run_id, position, turn_index, flow_node_id, "
            "flow_node_label, verdict, score, rationale) values (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                workspace_id,
                run_id,
                position,
                item.get("turn"),
                item.get("node"),
                item.get("label"),
                item["verdict"],
                item.get("score"),
                item.get("rationale", ""),
            ),
        )
    return run_id


@dataclass
class IssueEnv:
    app: FastAPI
    client: httpx.AsyncClient
    account: Account
    agent: SimAgent
    queue: RecordingQueue
    calls: dict[str, list[str]] = field(default_factory=dict)

    @property
    def ws(self) -> str:
        return self.account.workspace_id

    @property
    def headers(self) -> dict[str, str]:
        return self.account.headers

    def ctx(self) -> dict[str, Any]:
        state = self.app.state
        return {"db": state.db, "settings": state.settings, "jobs": self.queue, "redis": state.redis}

    async def run_jobs(self, *names: str, rounds: int = 10) -> int:
        from app.issues.install import FEATURE

        functions = dict(FEATURE.jobs)
        ran = 0
        for _ in range(rounds):
            todo = [j for j in self.queue.jobs if j.name in functions and (not names or j.name in names)]
            if not todo:
                break
            for job in todo:
                self.queue.jobs.remove(job)
                await functions[job.name](self.ctx(), *job.args)
                ran += 1
        return ran

    def seed_calls(
        self,
        n: int,
        *,
        verdict: str = "fail",
        reason: str = PRICE_REASON,
        evaluator: str = FACT,
        origin: str = "live",
        ago_hours: float = 1,
        version_id: str | None = None,
        tag: str = "fail",
        items: Sequence[Mapping[str, Any]] = (),
    ) -> list[str]:
        ids = []
        for i in range(n):
            call = seed_live_call(
                self.ws,
                (self.agent.agent_id, version_id or self.agent.version_id),
                lines=BOOKING_LINES,
                origin=origin,
                ended_ago=timedelta(hours=ago_hours, minutes=i),
            )
            seed_verdict(
                self.ws, call, self.agent.agent_id, evaluator, verdict, rationale=reason, items=items
            )
            ids.append(call)
        self.calls.setdefault(tag, []).extend(ids)
        return ids

    async def detect(self, **body: Any) -> dict[str, Any]:
        response = await self.client.post(
            "/v1/issues/detect",
            json={"agent_id": self.agent.agent_id, **body},
            headers={**self.headers, "Idempotency-Key": f"det-{uuid.uuid4().hex}"},
        )
        assert response.status_code == 202, response.text
        await self.run_jobs("detect_issues")
        latest = await self.client.get(
            "/v1/issues/detection", params={"agent_id": self.agent.agent_id}, headers=self.headers
        )
        assert latest.status_code == 200, latest.text
        result: dict[str, Any] = latest.json()
        return result

    async def issues(self, **params: Any) -> list[dict[str, Any]]:
        response = await self.client.get(
            "/v1/issues", params={"agent_id": self.agent.agent_id, **params}, headers=self.headers
        )
        assert response.status_code == 200, response.text
        items: list[dict[str, Any]] = response.json()["items"]
        return items

    async def issue(self, issue_id: str) -> dict[str, Any]:
        response = await self.client.get(f"/v1/issues/{issue_id}", headers=self.headers)
        assert response.status_code == 200, response.text
        body: dict[str, Any] = response.json()
        return body

    async def post(
        self, path: str, body: Mapping[str, Any] | None = None, *, key: bool = True
    ) -> httpx.Response:
        headers = dict(self.headers)
        if key:
            headers["Idempotency-Key"] = f"k-{uuid.uuid4().hex}"
        return await self.client.post(f"/v1{path}", json=dict(body or {}), headers=headers)


async def make_env(
    app: FastAPI, client: httpx.AsyncClient, *, prompt: str | None = None, **config: Any
) -> IssueEnv:
    account = await signup(client, app)
    kwargs: dict[str, Any] = dict(config)
    if prompt is not None:
        kwargs["prompt"] = prompt
    agent = await make_agent(client, account, **kwargs)
    enable(account.workspace_id, agent.agent_id, FACT, TOOLS)
    queue = RecordingQueue()
    return IssueEnv(app, client, account, agent, queue)


@pytest_asyncio.fixture
async def issue_env(app: FastAPI, client: httpx.AsyncClient) -> AsyncIterator[IssueEnv]:
    from app.evals import runtime as quality_runtime

    previous = getattr(app.state, "jobs", None)
    env = await make_env(app, client)
    app.state.jobs = env.queue
    quality_runtime.set_queue(env.queue)
    yield env
    app.state.jobs = previous
    quality_runtime.set_queue(previous)


# Stubbed 008 batch completion ------------------------------------------------------------------


def complete_batch(
    env: IssueEnv,
    experiment_id: str,
    verdicts: Mapping[str, Mapping[str, str]],
    *,
    failed: Sequence[str] = (),
    version: int = 1,
    versions: Mapping[tuple[str, str], int] | None = None,
) -> None:
    """Finish every run of a batch: base calls in ``failed`` fail; the others get a simulated call
    with ``verdicts[base_call_id] = {evaluator_id: "pass" | "fail"}``."""
    rows = owner_sql(
        "select id, base_call_id from simulation_runs where experiment_id = %s", (experiment_id,)
    )
    now = datetime.now(UTC)
    for run_id, base_call_id in rows:
        if base_call_id in failed:
            owner_sql(
                "update simulation_runs set status = 'failed', error_message = 'stub', finished_at = %s "
                "where id = %s",
                (now, run_id),
            )
            continue
        call_id = new_id("call")
        owner_sql(
            "insert into calls (id, workspace_id, agent_id, origin, channel, direction, status, created_at, "
            "ended_at, completed_at, pipeline_status, transcript, simulation_run_id) values (%s, %s, %s, "
            "'simulation', 'web', 'inbound', 'completed', %s, %s, %s, 'done', %s::jsonb, %s)",
            (
                call_id,
                env.ws,
                env.agent.agent_id,
                now,
                now,
                now,
                json.dumps({"items": [{"type": "message", "role": "agent", "text": "Hi"}]}),
                run_id,
            ),
        )
        owner_sql(
            "update simulation_runs set status = 'completed', output_call_id = %s, started_at = %s, "
            "finished_at = %s, cost_usd = 0.001 where id = %s",
            (call_id, now, now, run_id),
        )
        for evaluator, verdict in (verdicts.get(base_call_id) or {}).items():
            v = (versions or {}).get((base_call_id, evaluator), version)
            seed_verdict(env.ws, call_id, env.agent.agent_id, evaluator, verdict, version=v)
    owner_sql(
        "update simulation_experiments e set status = case when exists (select 1 from simulation_runs r "
        "where r.experiment_id = e.id and r.status = 'completed') then 'completed' else 'failed' end, "
        "completed_count = (select count(*) from simulation_runs r where r.experiment_id = e.id and "
        "r.status = 'completed'), failed_count = (select count(*) from simulation_runs r where "
        "r.experiment_id = e.id and r.status = 'failed'), cost_usd = 0.002, finished_at = %s where id = %s",
        (now, experiment_id),
    )


def verdict_plan(
    calls: Sequence[str], passes: int, evaluator: str = FACT, extra: Mapping[str, str] | None = None
) -> dict[str, dict[str, str]]:
    """The first ``passes`` calls pass ``evaluator``, the rest fail; ``extra`` adds fixed verdicts."""
    return {c: {evaluator: "pass" if i < passes else "fail", **(extra or {})} for i, c in enumerate(calls)}


async def ready_issue(env: IssueEnv, n: int = 8) -> dict[str, Any]:
    """Seed ``n`` failing calls, detect and return the issue."""
    env.seed_calls(n)
    await env.detect()
    [issue] = await env.issues()
    return issue
