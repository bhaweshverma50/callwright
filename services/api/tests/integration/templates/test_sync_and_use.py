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
        assert "automotive" not in [c["id"] for c in cats]
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
    assert again.unchanged == 7 and again.updated == 0


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
    assert cfg["tts"]["voice_id"] == "EXAVITQu4vr4xnSDxMaL" and cfg["tts"]["model"] == "eleven_flash_v2_5"
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


async def test_template_only_for_single_prompt(client: httpx.AsyncClient, account: Account) -> None:
    response = await create(client, account, name="x", agent_type="flow", template_id="banking-collections")
    assert response.status_code == 422
