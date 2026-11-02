"""Issues on a flow agent: node attribution, a node fix compiled through 008, apply updating the
flow graph (009; US2 scenario 2, FR-008, FR-021)."""

from __future__ import annotations

import httpx
from fastapi import FastAPI

from app.evals import runtime as quality_runtime
from tests.conftest import signup
from tests.flow_helpers import basic, create_flow, save
from tests.issues_support import FACT, IssueEnv, complete_batch, enable, verdict_plan
from tests.runtime_support import RecordingQueue, owner_sql
from tests.sim_support import SimAgent

NODE = "n_agent000"
ITEMS = [
    {
        "node": NODE,
        "label": "Triage",
        "verdict": "fail",
        "rationale": "Promised a same-day visit it cannot book.",
    }
]


async def test_node_fix_validates_and_applies_to_the_flow(app: FastAPI, client: httpx.AsyncClient) -> None:
    account = await signup(client, app)
    flow = (await create_flow(client, account))["flow"]
    assert (await save(client, account, flow, basic())).status_code == 200
    published = await client.post(
        f"/v1/flows/{flow['id']}/publish", json={"expected_revision": 2}, headers=account.headers
    )
    assert published.status_code == 201, published.text
    agent = SimAgent(flow["agent_id"], published.json()["agent_version_id"], {})
    enable(account.workspace_id, agent.agent_id, FACT)
    queue = RecordingQueue()
    previous = getattr(app.state, "jobs", None)
    app.state.jobs = queue
    quality_runtime.set_queue(queue)
    try:
        env = IssueEnv(app, client, account, agent, queue)
        env.seed_calls(8, items=ITEMS, reason="Triage failed.")
        env.seed_calls(3, verdict="pass", reason="ok", tag="guard", ago_hours=0.5)
        await env.detect()
        [issue] = await env.issues()
        assert issue["agent_type"] == "flow" and issue["flow_node_id"] == NODE
        detail = await env.issue(issue["issue_id"])
        assert detail["recommended_fix_kind"] == "node_prompt_edit"
        assert (
            detail["allowed_fix_kinds"][0] == "node_prompt_edit"
            and "prompt_edit" not in detail["allowed_fix_kinds"]
        )

        fix = await env.post(f"/issues/{issue['issue_id']}/fixes", {"mode": "ai"})
        assert fix.status_code == 201, fix.text
        body = fix.json()
        assert body["kind"] == "node_prompt_edit" and body["payload"]["node_id"] == NODE
        assert body["payload"]["current_instructions"] == "Help the caller."
        assert body["diff"][0]["path"] == f"/flow/graph/nodes[{NODE}]/config/instructions"

        started = await env.post(f"/issues/{issue['issue_id']}/validate", {})
        assert started.status_code == 202, started.text
        attempt = started.json()
        snapshot = owner_sql(
            "select config_snapshot from simulation_experiments where id = %s",
            (attempt["treatment_experiment_id"],),
        )[0][0]
        compiled = snapshot["flow"]["compiled"]["nodes"][NODE]["instructions"]
        assert body["payload"]["proposed_instructions"].splitlines()[-1] in compiled
        calls = attempt["affected_call_ids"]
        guard = {g: {FACT: "pass"} for g in attempt["guard_call_ids"]}
        complete_batch(env, attempt["control_experiment_id"], {**verdict_plan(calls, 1), **guard})
        complete_batch(env, attempt["treatment_experiment_id"], {**verdict_plan(calls, 6), **guard})
        await env.queue.enqueue("finalize_validation", env.ws, attempt["control_experiment_id"])
        await env.run_jobs("finalize_validation")
        assert (await env.issue(issue["issue_id"]))["status"] == "validated"

        applied = await env.post(f"/issues/{issue['issue_id']}/apply", {}, key=False)
        assert applied.status_code == 200, applied.text
        version = applied.json()["agent_version_id"]
        content_hash = owner_sql("select content_hash from agent_versions where id = %s", (version,))[0][0]
        assert content_hash == attempt["variant_config_hash"]
        graph = owner_sql("select graph from flows where id = %s", (flow["id"],))[0][0]
        triage = next(n for n in graph["nodes"] if n["id"] == NODE)
        assert triage["config"]["instructions"] == body["payload"]["proposed_instructions"]
    finally:
        app.state.jobs = previous
        quality_runtime.set_queue(previous)
