"""Template sync and use (T070, T103, FR-034, US5)."""

from __future__ import annotations

from pathlib import Path

import httpx
import yaml
from fastapi import FastAPI

from app.templates.jobs import SEED_DIR, sync
from tests.agent_helpers import create
from tests.conftest import Account


def write_seed(tmp: Path, *, voice: str | None = None, drop: str | None = None) -> None:
    for path in sorted(SEED_DIR.glob("*.yaml")):
        data = yaml.safe_load(path.read_text())
        if data["id"] == drop:
            continue
        if voice and data["id"] == "telecom-plan-upgrade":
            data["config"]["tts"]["voice_id"] = voice
            data["description"] = "Changed description."
        (tmp / path.name).write_text(yaml.safe_dump(data))


async def test_sync_upserts_and_deactivates(
    client: httpx.AsyncClient, account: Account, app: FastAPI, tmp_path: Path
) -> None:
    write_seed(tmp_path, voice="nope-not-a-voice", drop="automotive-roadside-ev")
    try:
        report = await sync(app.state.db, tmp_path)
        assert (report.inserted, report.updated, report.deactivated) == (0, 1, 1)
        listed = (await client.get("/v1/templates", headers=account.headers)).json()["items"]
        assert "automotive-roadside-ev" not in [t["id"] for t in listed]
        inactive = await client.get("/v1/templates/automotive-roadside-ev", headers=account.headers)
        assert inactive.status_code == 404
        refused = await create(client, account, name="x", template_id="automotive-roadside-ev")
        assert refused.status_code == 404
        cats = (await client.get("/v1/templates/categories", headers=account.headers)).json()["items"]
        assert {c["id"]: c["count"] for c in cats}["automotive"] == 2
        # A voice the catalog does not know is replaced with the language default, with a notice.
        used = await create(client, account, name="Upgrade", template_id="telecom-plan-upgrade")
        assert used.status_code == 201
        body = used.json()
        assert body["draft_config"]["tts"]["voice_id"] == "EXAVITQu4vr4xnSDxMaL"
        assert {"pointer": "/tts/voice_id", "code": "component_replaced"} in [
            {k: w[k] for k in ("pointer", "code")} for w in body["warnings"]
        ]
    finally:
        report = await sync(app.state.db)
        assert report.inserted == 0
    again = await sync(app.state.db)
    assert again.unchanged == 26 and again.updated == 0


async def test_use_template_overlays_defaults(client: httpx.AsyncClient, account: Account) -> None:
    response = await create(
        client,
        account,
        name="Clinic triage",
        template_id="healthcare-triage-booking",
        headers={"Idempotency-Key": "tmpl-1"},
    )
    assert response.status_code == 201
    agent = response.json()
    assert agent["template_id"] == "healthcare-triage-booking"
    cfg = agent["draft_config"]
    assert cfg["language"] == "en-US" and cfg["llm"] == {
        "provider": "azure_openai",
        "model": "gpt-5.1",
        "temperature": 1.0,
    }
    assert cfg["tts"]["voice_id"] == "EXAVITQu4vr4xnSDxMaL"
    assert cfg["tts"]["model"] == "eleven_multilingual_v2"
    assert cfg["dynamic_variables"] == [
        {"name": "company_name", "default": "Acme Health Clinic", "description": None}
    ]
    assert cfg["call_behavior"]["max_duration_s"] == 600 and cfg["noise_cancellation"] == {
        "provider": "sanas",
        "model": "vi",
    }
    assert "Thank you for calling {{company_name}}" in cfg["begin_message"]
    history = (await client.get(f"/v1/agents/{agent['id']}/versions", headers=account.headers)).json()
    assert history["items"][0]["source"] == "template"
    assert (
        history["items"][0]["note"]
        == 'Created from template "Symptom triage and booking" (healthcare-triage-booking)'
    )
    again = await create(
        client,
        account,
        name="Clinic triage",
        template_id="healthcare-triage-booking",
        headers={"Idempotency-Key": "tmpl-1"},
    )
    assert again.json()["id"] == agent["id"]
    count = (await client.get("/v1/agents?search=Clinic triage", headers=account.headers)).json()["total"]
    assert count == 1


async def test_template_with_body_overrides(client: httpx.AsyncClient, account: Account) -> None:
    response = await create(
        client,
        account,
        name="Collections DE",
        template_id="banking-collections",
        config={"language": "de", "call_behavior": {"max_duration_s": 900}},
    )
    assert response.status_code == 201
    cfg = response.json()["draft_config"]
    assert cfg["language"] == "de" and cfg["call_behavior"]["max_duration_s"] == 900
    assert "{{overdue_amount}}" in cfg["prompt"]


async def test_template_type_must_match(client: httpx.AsyncClient, account: Account) -> None:
    response = await create(client, account, name="x", agent_type="flow", template_id="banking-collections")
    assert response.status_code == 422
    assert response.json()["errors"][0]["pointer"] == "/template_id"
    assert "single-prompt" in response.json()["errors"][0]["message"]
    flow_in_single = await create(
        client, account, name="x", agent_type="single_prompt", template_id="healthcare-appointment-booking"
    )
    assert flow_in_single.status_code == 422
    assert flow_in_single.json()["errors"][0]["pointer"] == "/template_id"
    assert "flow agent" in flow_in_single.json()["errors"][0]["message"]
    via_flows = await client.post(
        "/v1/flows",
        json={"name": "x", "language": "en-US", "template_id": "banking-collections"},
        headers=account.headers,
    )
    assert via_flows.status_code == 422
    assert via_flows.json()["errors"][0]["pointer"] == "/template_id"


async def test_create_flow_agent_from_template(client: httpx.AsyncClient, account: Account) -> None:
    response = await client.post(
        "/v1/flows",
        json={"name": "Claims line", "language": "en-US", "template_id": "insurance-claim-intake"},
        headers=account.headers,
    )
    assert response.status_code == 201, response.text
    body = response.json()
    flow = body["flow"]
    assert len(flow["graph"]["nodes"]) >= 8
    assert {n["type"] for n in flow["graph"]["nodes"]} >= {"start", "task", "condition", "transfer", "end"}
    assert flow["last_validation"]["errors"] == 0
    agent = (await client.get(f"/v1/agents/{body['agent_id']}", headers=account.headers)).json()
    assert agent["type"] == "flow" and agent["template_id"] == "insurance-claim-intake"
    assert "graph" not in agent["draft_config"]
    assert "claims intake assistant" in agent["draft_config"]["prompt"]
    assert [v["name"] for v in agent["draft_config"]["dynamic_variables"]] == ["company_name"]
    history = (await client.get(f"/v1/agents/{agent['id']}/versions", headers=account.headers)).json()
    assert history["items"][0]["source"] == "template"


async def test_template_filters_and_counts(client: httpx.AsyncClient, account: Account) -> None:
    async def ids(query: str) -> list[str]:
        r = await client.get(f"/v1/templates?{query}", headers=account.headers)
        assert r.status_code == 200, r.text
        return [t["id"] for t in r.json()["items"]]

    async def counts(query: str) -> dict[str, int]:
        r = await client.get(f"/v1/templates/categories?{query}", headers=account.headers)
        assert r.status_code == 200, r.text
        return {c["id"]: c["count"] for c in r.json()["items"]}

    everything = await ids("")
    assert len(everything) == 26
    flows = await ids("agent_type=flow")
    assert len(flows) == 9 and set(flows) <= set(everything)
    inbound = await ids("direction=inbound")
    outbound = await ids("direction=outbound")
    assert sorted(inbound + outbound) == sorted(everything)
    both = await ids("agent_type=flow&direction=outbound")
    assert set(both) == set(flows) & set(outbound) and both
    # Counts follow the other filters; each total equals the list under the same filters.
    for query in ("", "agent_type=flow", "direction=inbound", "agent_type=single_prompt&direction=outbound"):
        assert sum((await counts(query)).values()) == len(await ids(query)), query
    assert len(await counts("")) == 10
    assert (await counts("agent_type=flow&direction=inbound"))["insurance"] == 1
    assert "hospitality" not in await counts("agent_type=flow")
    # The category chip count is what selecting it returns.
    by_cat = await counts("direction=outbound")
    for cat, n in by_cat.items():
        assert len(await ids(f"direction=outbound&category={cat}")) == n
    assert (await client.get("/v1/templates?direction=sideways", headers=account.headers)).status_code == 422
    summary = (await client.get("/v1/templates?agent_type=flow", headers=account.headers)).json()["items"][0]
    assert summary["agent_type"] == "flow"
