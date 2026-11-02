"""Target resolution and snapshot hashing (008 T007; research R3, FR-012)."""

from __future__ import annotations

import copy

import httpx
import pytest
from fastapi import FastAPI

from app.agent_versions.canonical import canonical_json
from app.agents.models import Agent
from app.core.errors import ProblemError
from app.simulator.targets import (
    agent_model,
    canonical_hash,
    resolve_target,
    runnable_problem,
)
from tests.conftest import Account
from tests.sim_support import make_agent


def test_canonical_hash_ignores_key_order_and_whitespace() -> None:
    a = {"prompt": "Hi", "llm": {"model": "gpt-5.1", "provider": "openai"}, "n": 1.0}
    b = {"n": 1, "llm": {"provider": "openai", "model": "gpt-5.1"}, "prompt": "Hi"}
    assert canonical_hash(a) == canonical_hash(b)
    assert canonical_json(a) == '{"llm":{"model":"gpt-5.1","provider":"openai"},"n":1,"prompt":"Hi"}'
    assert canonical_hash({**a, "prompt": "Hello"}) != canonical_hash(a)
    assert len(canonical_hash(a)) == 64


def test_runnable_and_model_rules() -> None:
    assert runnable_problem("single_prompt", {"prompt": "  "}) is not None
    assert runnable_problem("single_prompt", {"prompt": "Be nice"}) is None
    assert runnable_problem("flow", {"flow": {"compiled": {"nodes": {"s": {"type": "start"}}}}}) is not None
    flow = {"flow": {"compiled": {"nodes": {"s": {"type": "start"}, "a": {"type": "agent"}}}}}
    assert runnable_problem("flow", flow) is None
    assert agent_model({"llm": {"provider": "openai", "model": "gpt-5-mini"}}) == "openai/gpt-5-mini"
    assert agent_model({}) == "azure_openai/gpt-5.1"


async def _agent(app: FastAPI, ws: str, agent_id: str) -> Agent:
    async with app.state.db.transaction(workspace_id=ws) as session:
        agent = await session.get(Agent, agent_id)
        assert agent is not None
        return agent


async def test_published_draft_and_version_targets(
    app: FastAPI, client: httpx.AsyncClient, account: Account
) -> None:
    ws = account.workspace_id
    sim = await make_agent(client, account)
    agent = await _agent(app, ws, sim.agent_id)
    async with app.state.db.transaction(workspace_id=ws) as session:
        published = await resolve_target(session, agent, {"type": "published"})
        draft = await resolve_target(session, agent, None, default="draft")
        version = await resolve_target(
            session, agent, {"type": "version", "agent_version_id": sim.version_id}
        )
    assert published.agent_version_id == sim.version_id and published.target_type == "published"
    assert published.config_hash == canonical_hash(published.config)
    assert draft.target_type == "draft" and draft.config["prompt"] == published.config["prompt"]
    assert version.config_hash == published.config_hash
    assert published.variant_diff is None


async def test_unpublished_agent_and_bad_version_are_refused(
    app: FastAPI, client: httpx.AsyncClient, account: Account
) -> None:
    ws = account.workspace_id
    sim = await make_agent(client, account, published=False)
    other = await make_agent(client, account)
    agent = await _agent(app, ws, sim.agent_id)
    async with app.state.db.transaction(workspace_id=ws) as session:
        with pytest.raises(ProblemError) as unpublished:
            await resolve_target(session, agent, {"type": "published"})
        with pytest.raises(ProblemError) as foreign:
            await resolve_target(session, agent, {"type": "version", "agent_version_id": other.version_id})
        with pytest.raises(ProblemError) as missing:
            await resolve_target(session, agent, {"type": "version"})
        with pytest.raises(ProblemError) as no_variant:
            await resolve_target(session, agent, {"type": "variant", "config": {}}, allow_variant=True)
        with pytest.raises(ProblemError) as variant_not_allowed:
            await resolve_target(session, agent, {"type": "variant"}, allow_variant=False)
    assert unpublished.value.status == 409 and unpublished.value.code == "agent_not_published"
    assert foreign.value.status == 422 and foreign.value.errors
    assert foreign.value.errors[0]["pointer"] == "/target/agent_version_id"
    assert missing.value.status == 422
    assert no_variant.value.errors and no_variant.value.errors[0]["pointer"] == "/target/config"
    assert (
        variant_not_allowed.value.errors and variant_not_allowed.value.errors[0]["pointer"] == "/target/type"
    )


async def test_variant_is_validated_hashed_and_diffed(
    app: FastAPI, client: httpx.AsyncClient, account: Account
) -> None:
    ws = account.workspace_id
    sim = await make_agent(client, account)
    agent = await _agent(app, ws, sim.agent_id)
    async with app.state.db.transaction(workspace_id=ws) as session:
        base = await resolve_target(session, agent, {"type": "published"})
        config = copy.deepcopy(base.config)
        config["prompt"] = "You book cleanings. Always confirm the date twice."
        variant = await resolve_target(
            session, agent, {"type": "variant", "config": config, "label": "Confirm twice"}
        )
        broken = copy.deepcopy(base.config)
        broken["llm"] = {"provider": "openai", "model": "no-such-model"}
        with pytest.raises(ProblemError) as invalid:
            await resolve_target(session, agent, {"type": "variant", "config": broken})
    assert variant.target_type == "variant" and variant.agent_version_id == sim.version_id
    assert variant.variant_label == "Confirm twice"
    assert variant.config_hash == canonical_hash(config) != base.config_hash
    assert variant.variant_diff == [
        {"op": "replace", "path": "/prompt", "value": config["prompt"], "old": base.config["prompt"]}
    ]
    assert invalid.value.status == 422
    assert invalid.value.errors and all(
        e["pointer"].startswith("/target/config") for e in invalid.value.errors
    )


async def test_flow_variant_with_an_edited_graph_is_compiled(
    app: FastAPI, client: httpx.AsyncClient, account: Account
) -> None:
    from tests.flow_helpers import basic, create_flow, save

    h = account.headers
    flow = (await create_flow(client, account))["flow"]
    assert (await save(client, account, flow, basic())).status_code == 200
    published = await client.post(f"/v1/flows/{flow['id']}/publish", json={"expected_revision": 2}, headers=h)
    assert published.status_code == 201, published.text
    agent = await _agent(app, account.workspace_id, flow["agent_id"])
    async with app.state.db.transaction(workspace_id=account.workspace_id) as session:
        base = await resolve_target(session, agent, {"type": "published"})
        draft = (await client.get(f"/v1/agents/{agent.id}", headers=h)).json()["draft_config"]
        graph = copy.deepcopy(base.config["flow"]["graph"])
        for n in graph["nodes"]:
            if n["type"] == "agent":
                n["config"]["instructions"] = "Help the caller. Always confirm the date twice."
        variant = await resolve_target(
            session, agent, {"type": "variant", "config": {**draft, "flow": {"graph": graph}}}
        )
        compiled = variant.config["flow"]["compiled"]
        assert any("confirm the date twice" in str(n.get("instructions")) for n in compiled["nodes"].values())
        assert variant.config_hash != base.config_hash
        # No graph: the base version's compiled flow is kept.
        same = await resolve_target(session, agent, {"type": "variant", "config": dict(draft)})
        assert same.config["flow"]["compiled"] == base.config["flow"]["compiled"]
        broken = copy.deepcopy(graph)
        broken["nodes"] = [n for n in broken["nodes"] if n["type"] != "start"]
        with pytest.raises(ProblemError) as invalid:
            await resolve_target(
                session, agent, {"type": "variant", "config": {**draft, "flow": {"graph": broken}}}
            )
    assert invalid.value.status == 422
    assert invalid.value.errors and invalid.value.errors[0]["pointer"].startswith("/target/config/flow")
