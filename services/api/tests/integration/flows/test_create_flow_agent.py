"""Creating a flow agent (004 T013; US1 scenarios 1 and 2, FR-001, FR-003, research R15)."""

from __future__ import annotations

import httpx

from tests.conftest import Account
from tests.flow_helpers import create_flow


async def test_agent_and_flow_are_created_together(client: httpx.AsyncClient, account: Account) -> None:
    body = await create_flow(client, account, "Clinic intake", "en-GB")
    flow = body["flow"]
    assert body["warnings"] == []
    assert flow["agent_id"] == body["agent_id"] and flow["name"] == "Clinic intake" and flow["revision"] == 1
    assert [n["type"] for n in flow["graph"]["nodes"]] == ["start", "agent", "end"]
    assert flow["last_validation"]["errors"] == 0
    agent = (await client.get(f"/v1/agents/{body['agent_id']}", headers=account.headers)).json()
    assert agent["type"] == "flow" and agent["name"] == "Clinic intake"
    config = agent["draft_config"]
    assert config["language"] == "en-GB"
    assert config["stt"]["provider"] == "deepgram"
    assert config["tts"]["provider"] == "elevenlabs" and config["tts"]["voice_id"]
    by_agent = await client.get(f"/v1/agents/{body['agent_id']}/flow", headers=account.headers)
    assert by_agent.status_code == 200 and by_agent.json()["id"] == flow["id"]
    assert by_agent.headers["etag"] == '"1"'


async def test_empty_name_is_refused_and_nothing_is_created(
    client: httpx.AsyncClient, account: Account
) -> None:
    before = (await client.get("/v1/agents", headers=account.headers)).json()["total"]
    response = await client.post(
        "/v1/flows", json={"name": "   ", "language": "en-US"}, headers=account.headers
    )
    assert response.status_code == 422
    assert "Agent name is required" in response.text
    assert (await client.get("/v1/agents", headers=account.headers)).json()["total"] == before


async def test_unknown_language_falls_back_with_a_warning(
    client: httpx.AsyncClient, account: Account
) -> None:
    body = await create_flow(client, account, "Lingua", "xx-YY")
    assert body["warnings"] and "en-US" in body["warnings"][0]
    agent = (await client.get(f"/v1/agents/{body['agent_id']}", headers=account.headers)).json()
    assert agent["draft_config"]["language"] == "en-US"


async def test_single_prompt_agent_has_no_flow(client: httpx.AsyncClient, account: Account) -> None:
    from tests.agent_helpers import create_ok

    agent = await create_ok(client, account)
    response = await client.get(f"/v1/agents/{agent['id']}/flow", headers=account.headers)
    assert response.status_code == 409 and response.json()["code"] == "agent_not_flow"


async def test_duplicating_a_flow_agent_copies_the_flow(client: httpx.AsyncClient, account: Account) -> None:
    body = await create_flow(client, account, "Original")
    dup = await client.post(f"/v1/agents/{body['agent_id']}/duplicate", headers=account.headers)
    assert dup.status_code == 201, dup.text
    copy_flow = (await client.get(f"/v1/agents/{dup.json()['id']}/flow", headers=account.headers)).json()
    assert copy_flow["name"] == "Original (copy)"
    assert copy_flow["graph"]["nodes"] == body["flow"]["graph"]["nodes"]
