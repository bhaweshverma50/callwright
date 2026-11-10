"""List and search performance at 1,000 agents (T048, SC-005; plan target p95 under 300 ms)."""

from __future__ import annotations

import time

import httpx
from fastapi import FastAPI
from sqlalchemy import insert

from app.agent_versions.canonical import content_hash
from app.agent_versions.models import AgentVersion
from app.agent_versions.service import summary_of
from app.agents.defaults import default_config
from app.agents.models import Agent
from app.core.ids import new_id
from tests.conftest import signup
from tests.perf import SLACK

AGENTS = 1000
RUNS = 20


async def test_search_p95_under_300_ms(client: httpx.AsyncClient, app: FastAPI) -> None:
    account = await signup(client, app)
    config = default_config("single_prompt")
    config["prompt"] = "Perf"
    digest = content_hash(config)
    agents, versions = [], []
    for i in range(AGENTS):
        agent_id, version_id = new_id("agt"), new_id("agv")
        agents.append(
            {
                "id": agent_id,
                "workspace_id": account.workspace_id,
                "name": f"Agent {i:04d} {'clinic' if i % 10 == 0 else 'desk'}",
                "type": "single_prompt",
                "language": "en-US",
                "draft_config": config,
                "draft_revision": 1,
                "draft_version_id": version_id,
            }
        )
        versions.append(
            {
                "id": version_id,
                "workspace_id": account.workspace_id,
                "agent_id": agent_id,
                "version_number": 1,
                "schema_version": 1,
                "config": config,
                "content_hash": digest,
                "source": "create",
                "summary": summary_of(config),
                "publish_blockers": [],
            }
        )
    async with app.state.db.transaction(workspace_id=account.workspace_id) as session:
        await session.execute(insert(Agent), agents)
        await session.execute(insert(AgentVersion), versions)

    timings: list[float] = []
    for i in range(RUNS):
        query = "clinic" if i % 2 == 0 else f"Agent 0{i:02d}"
        start = time.perf_counter()
        response = await client.get(f"/v1/agents?search={query}&page_size=20", headers=account.headers)
        timings.append(time.perf_counter() - start)
        assert response.status_code == 200
    first = await client.get("/v1/agents?search=clinic", headers=account.headers)
    assert first.json()["total"] == AGENTS // 10
    timings.sort()
    p95 = timings[int(len(timings) * 0.95) - 1]
    assert p95 < 0.3 * SLACK, f"p95 {p95 * 1000:.0f} ms"
