"""contracts/agents.yaml: create, defaults, validate, get, rename, save draft (T025)."""

from __future__ import annotations

import httpx

from tests.agent_helpers import blank_config, create, create_ok, save
from tests.conftest import Account
from tests.contract.conftest import check

MISSING_AGENT = "/v1/agents/agt_01ARZ3NDEKTSV4RRFFQ69G5FAV"


async def test_create_201_401_404_422(client: httpx.AsyncClient, account: Account) -> None:
    created = check(await create(client, account))
    assert created.status_code == 201
    assert created.headers["etag"] == '"1"'
    body = created.json()
    assert body["draft_version"]["version_number"] == 1 and body["published_version"] is None
    assert check(await client.post("/v1/agents", json={"name": "x", "type": "flow"})).status_code == 401
    missing = check(await create(client, account, template_id="no-such-template"))
    assert missing.status_code == 404
    bad = check(await create(client, account, config={"prompt": ""}))
    assert bad.status_code == 422
    assert {"pointer": "/prompt", "code": "required"} in [
        {k: e[k] for k in ("pointer", "code")} for e in bad.json()["errors"]
    ]


async def test_defaults_200_401(client: httpx.AsyncClient, account: Account) -> None:
    response = check(
        await client.get("/v1/agents/defaults?type=single_prompt&language=hi", headers=account.headers)
    )
    assert response.status_code == 200
    assert response.json()["stt"]["provider"] == "sarvam"
    assert response.json()["call_behavior"]["end_on_silence_s"] == 30
    assert check(await client.get("/v1/agents/defaults")).status_code == 401


async def test_validate_200_401(client: httpx.AsyncClient, account: Account) -> None:
    response = check(
        await client.post(
            "/v1/agents/validate",
            json={"type": "single_prompt", "config": {"schema_version": 1}},
            headers=account.headers,
        )
    )
    assert response.status_code == 200
    assert response.json()["valid"] is False and response.json()["errors"]
    invalid = check(
        await client.post(
            "/v1/agents/validate",
            json={
                "type": "single_prompt",
                "config": {"prompt": "", "call_behavior": {"ring_duration_ms": -1}, "tts": {"voice_id": ""}},
            },
            headers=account.headers,
        )
    )
    assert {e["pointer"] for e in invalid.json()["errors"]} >= {
        "/prompt",
        "/call_behavior/ring_duration_ms",
        "/tts/voice_id",
    }
    ok = check(
        await client.post(
            "/v1/agents/validate",
            json={"type": "single_prompt", "config": blank_config()},
            headers=account.headers,
        )
    )
    assert ok.json()["valid"] is True
    assert check(await client.post("/v1/agents/validate", json={})).status_code == 401


async def test_get_200_401_404(client: httpx.AsyncClient, account: Account) -> None:
    agent = await create_ok(client, account)
    response = check(await client.get(f"/v1/agents/{agent['id']}", headers=account.headers))
    assert response.status_code == 200 and response.headers["etag"] == '"1"'
    assert check(await client.get(f"/v1/agents/{agent['id']}")).status_code == 401
    assert check(await client.get(MISSING_AGENT, headers=account.headers)).status_code == 404


async def test_rename_200_404_422(client: httpx.AsyncClient, account: Account) -> None:
    agent = await create_ok(client, account)
    url = f"/v1/agents/{agent['id']}"
    renamed = check(await client.patch(url, json={"name": "Front desk"}, headers=account.headers))
    assert renamed.status_code == 200 and renamed.json()["name"] == "Front desk"
    assert (
        check(await client.patch(MISSING_AGENT, json={"name": "x"}, headers=account.headers)).status_code
        == 404
    )
    assert check(await client.patch(url, json={"name": ""}, headers=account.headers)).status_code == 422


async def test_save_draft_200_404_412_422(client: httpx.AsyncClient, account: Account) -> None:
    agent = await create_ok(client, account)
    config = blank_config(prompt="Hello {{customer_name}}.")
    config["dynamic_variables"] = [{"name": "customer_name", "default": "there"}]
    saved = check(await save(client, account, agent, config, note="first prompt"))
    assert saved.status_code == 200
    assert saved.json()["created"] is True and saved.json()["version"]["version_number"] == 2
    assert saved.headers["etag"] == '"2"'
    stale = check(await save(client, account, agent, config, revision=1))
    assert stale.status_code == 412
    assert stale.json()["code"] == "draft_changed" and stale.json()["current_revision"] == 2
    missing = check(
        await client.put(
            f"{MISSING_AGENT}/draft", json={"config": config}, headers={**account.headers, "If-Match": '"1"'}
        )
    )
    assert missing.status_code == 404
    bad = check(await save(client, account, saved.json()["agent"], {**config, "prompt": ""}))
    assert bad.status_code == 422
