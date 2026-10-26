"""Contract tests for the tool library (005 T016, T034, T082, T093)."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable
from typing import Any

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI

from app.tools import router as tools_router
from tests.agent_helpers import create_ok
from tests.conftest import Account, signup
from tests.contract.conftest import check

MISSING_TOOL = "tool_01ARZ3NDEKTSV4RRFFQ69G5FAV"
MISSING_AGENT = "agt_01ARZ3NDEKTSV4RRFFQ69G5FAV"


def end_call(name: str = "end_call", **config: Any) -> dict[str, Any]:
    return {"type": "end_call", "name": name, "description": "End the call", "config": config}


def transfer(name: str = "transfer_desk", number: str = "+14155550100") -> dict[str, Any]:
    return {
        "type": "transfer_call",
        "name": name,
        "description": "Transfer to the front desk",
        "config": {"routing_type": "static", "number": number},
    }


def http_tool(name: str = "check_availability", **config: Any) -> dict[str, Any]:
    return {
        "type": "http",
        "name": name,
        "description": "Look up slots",
        "config": {
            "url": "https://api.example.com/slots",
            "parameters": {
                "type": "object",
                "properties": {"date": {"type": "string"}},
                "required": ["date"],
            },
            **config,
        },
    }


async def make(client: httpx.AsyncClient, account: Account, body: dict[str, Any]) -> dict[str, Any]:
    response = check(await client.post("/v1/tools", json=body, headers=account.headers))
    assert response.status_code == 201, response.text
    created: dict[str, Any] = response.json()
    return created


async def test_create_list_get_patch(client: httpx.AsyncClient, account: Account) -> None:
    tool = await make(client, account, end_call(message="Goodbye!"))
    assert tool["id"].startswith("tool_") and tool["usage_count"] == 0
    assert tool["config"] == {"message": "Goodbye!"}
    listed = check(await client.get("/v1/tools?type=end_call", headers=account.headers))
    assert [t["id"] for t in listed.json()["items"]] == [tool["id"]]
    assert check(await client.get("/v1/tools")).status_code == 401
    searched = check(await client.get("/v1/tools?search=nothing-like-this", headers=account.headers))
    assert searched.json()["total"] == 0
    got = check(await client.get(f"/v1/tools/{tool['id']}", headers=account.headers))
    assert got.json()["name"] == "end_call"
    patched = check(
        await client.patch(f"/v1/tools/{tool['id']}", json={"name": "hang_up"}, headers=account.headers)
    )
    assert patched.status_code == 200 and patched.json()["name"] == "hang_up"
    assert check(await client.get(f"/v1/tools/{MISSING_TOOL}", headers=account.headers)).status_code == 404


async def test_validation_errors_name_fields(client: httpx.AsyncClient, account: Account) -> None:
    bad = check(await client.post("/v1/tools", json=end_call("kb_search"), headers=account.headers))
    assert bad.status_code == 422 and bad.json()["errors"][0]["pointer"] == "/name"
    legacy = transfer()
    legacy["config"]["transfer_destination"] = {"number": "+14155550100"}
    refused = check(await client.post("/v1/tools", json=legacy, headers=account.headers))
    assert refused.status_code == 422
    assert [e["pointer"] for e in refused.json()["errors"]] == ["/config/transfer_destination"]
    mocked = {**end_call(), "mock_response": "{}"}
    refused = check(await client.post("/v1/tools", json=mocked, headers=account.headers))
    assert refused.status_code == 422 and refused.json()["errors"][0]["pointer"] == "/mock_response"
    unknown = {**end_call(), "colour": "red"}
    assert check(await client.post("/v1/tools", json=unknown, headers=account.headers)).status_code == 422
    plain_http = http_tool(url="http://api.example.com/x")
    refused = check(await client.post("/v1/tools", json=plain_http, headers=account.headers))
    assert refused.json()["errors"][0]["code"] == "https_required"


async def test_presets(client: httpx.AsyncClient, account: Account) -> None:
    body = check(await client.get("/v1/tools/presets", headers=account.headers)).json()
    ids = [p["preset_id"] for p in body["items"]]
    assert ids == ["end_call_polite", "transfer_to_person", "press_digit_ivr", "http_check_availability"]


async def test_secret_headers_masked_kept_and_replaced(client: httpx.AsyncClient, account: Account) -> None:
    body = http_tool(headers=[{"name": "Authorization", "value": "Bearer sk-live-12345678", "secret": True}])
    tool = await make(client, account, body)
    header = tool["config"]["headers"][0]
    assert header["value"] is None and header["masked_value"] == "****5678" and header["secret_ref"]
    assert "sk-live" not in json.dumps(tool)
    kept = check(
        await client.patch(
            f"/v1/tools/{tool['id']}",
            json={"config": {**body["config"], "headers": [{"name": "Authorization", "secret": True}]}},
            headers=account.headers,
        )
    ).json()
    assert kept["config"]["headers"][0]["secret_ref"] == header["secret_ref"]
    replaced = check(
        await client.patch(
            f"/v1/tools/{tool['id']}",
            json={
                "config": {
                    **body["config"],
                    "headers": [{"name": "Authorization", "secret": True, "value": "Bearer new-token-9999"}],
                }
            },
            headers=account.headers,
        )
    ).json()
    assert replaced["config"]["headers"][0]["masked_value"] == "****9999"
    assert replaced["config"]["headers"][0]["secret_ref"] != header["secret_ref"]
    missing = check(
        await client.post(
            "/v1/tools",
            json=http_tool("other", headers=[{"name": "X-Key", "secret": True}]),
            headers=account.headers,
        )
    )
    assert missing.status_code == 422 and missing.json()["errors"][0]["pointer"] == "/config/headers/0/value"


async def test_duplicate_usages_and_delete(client: httpx.AsyncClient, account: Account) -> None:
    tool = await make(client, account, end_call())
    copy = check(await client.post(f"/v1/tools/{tool['id']}/duplicate", headers=account.headers))
    assert copy.status_code == 201 and copy.json()["name"] == "end_call_copy"
    assert (
        check(await client.post(f"/v1/tools/{MISSING_TOOL}/duplicate", headers=account.headers)).status_code
        == 404
    )
    agent = await create_ok(client, account)
    attached = check(
        await client.put(
            f"/v1/agents/{agent['id']}/tools", json={"tool_ids": [tool["id"]]}, headers=account.headers
        )
    )
    assert attached.status_code == 200 and [t["id"] for t in attached.json()["tools"]] == [tool["id"]]
    usages = check(await client.get(f"/v1/tools/{tool['id']}/usages", headers=account.headers)).json()
    assert usages["items"][0]["agent_id"] == agent["id"] and usages["items"][0]["in_draft"] is True
    assert (
        check(await client.get(f"/v1/tools/{tool['id']}", headers=account.headers)).json()["usage_count"] == 1
    )
    in_use = check(await client.delete(f"/v1/tools/{tool['id']}", headers=account.headers))
    assert in_use.status_code == 409 and in_use.json()["code"] == "tool_in_use"
    assert in_use.json()["agents"][0]["agent_id"] == agent["id"]
    forced = check(await client.delete(f"/v1/tools/{tool['id']}?force=true", headers=account.headers))
    assert forced.status_code == 200 and forced.json()["detached_agent_ids"] == [agent["id"]]
    after = check(await client.get(f"/v1/agents/{agent['id']}/tools", headers=account.headers))
    assert after.json()["tools"] == []
    assert check(await client.delete(f"/v1/tools/{MISSING_TOOL}", headers=account.headers)).status_code == 404


async def test_agent_tool_set_rules(client: httpx.AsyncClient, account: Account) -> None:
    agent = await create_ok(client, account)
    one = await make(client, account, end_call("same_name"))
    two = await make(client, account, end_call("same_name"))
    conflict = check(
        await client.put(
            f"/v1/agents/{agent['id']}/tools",
            json={"tool_ids": [one["id"], two["id"]]},
            headers=account.headers,
        )
    )
    assert conflict.status_code == 422 and conflict.json()["code"] == "tool_name_conflict"
    too_many = check(
        await client.put(
            f"/v1/agents/{agent['id']}/tools",
            json={"tool_ids": [f"tool_{i:026d}" for i in range(26)]},
            headers=account.headers,
        )
    )
    assert too_many.status_code == 422
    unknown = check(
        await client.put(
            f"/v1/agents/{agent['id']}/tools", json={"tool_ids": [MISSING_TOOL]}, headers=account.headers
        )
    )
    assert unknown.status_code == 422 and unknown.json()["errors"][0]["code"] == "missing_reference"
    missing_agent = check(
        await client.put(f"/v1/agents/{MISSING_AGENT}/tools", json={"tool_ids": []}, headers=account.headers)
    )
    assert missing_agent.status_code == 404
    assert (
        check(await client.get(f"/v1/agents/{MISSING_AGENT}/tools", headers=account.headers)).status_code
        == 404
    )


async def test_other_workspace_cannot_see_tools(
    client: httpx.AsyncClient, account: Account, app: FastAPI
) -> None:
    tool = await make(client, account, end_call())
    other = await signup(client, app)
    assert check(await client.get(f"/v1/tools/{tool['id']}", headers=other.headers)).status_code == 404


async def test_mock_coverage(client: httpx.AsyncClient, account: Account) -> None:
    agent = await create_ok(client, account)
    no_mock = await make(client, account, http_tool("lookup_a"))
    with_mock = await make(client, account, {**http_tool("lookup_b"), "mock_response": '{"slots": []}'})
    hangup = await make(client, account, end_call())
    await client.put(
        f"/v1/agents/{agent['id']}/tools",
        json={"tool_ids": [no_mock["id"], with_mock["id"], hangup["id"]]},
        headers=account.headers,
    )
    coverage = check(
        await client.get(f"/v1/agents/{agent['id']}/tools/mock-coverage", headers=account.headers)
    )
    assert coverage.json() == {
        "ready": False,
        "missing": [{"source": "tool", "tool_id": no_mock["id"], "name": "lookup_a", "tool_type": "http"}],
    }
    assert (
        check(
            await client.get(f"/v1/agents/{MISSING_AGENT}/tools/mock-coverage", headers=account.headers)
        ).status_code
        == 404
    )


# Test runs ------------------------------------------------------------------------------------

Handler = Callable[[httpx.Request], httpx.Response]


@pytest_asyncio.fixture
async def upstream(app: FastAPI) -> AsyncIterator[list[httpx.Request]]:
    seen: list[httpx.Request] = []
    responder: dict[str, Handler] = {
        "fn": lambda r: httpx.Response(200, json={"data": {"slots": [{"time": "10:00"}]}})
    }

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return responder["fn"](request)

    async def resolver(host: str, port: int) -> list[str]:
        return ["10.1.1.1"] if host == "internal.example.com" else ["93.184.216.34"]

    app.state.tool_http = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    tools_router.test_run_resolver = resolver
    try:
        yield seen
    finally:
        await app.state.tool_http.aclose()
        app.state.tool_http = None
        tools_router.test_run_resolver = None


async def test_test_run_inline_and_saved(
    client: httpx.AsyncClient, account: Account, upstream: list[httpx.Request]
) -> None:
    body = http_tool(
        headers=[{"name": "X-Api-Key", "value": "secret-value-4321", "secret": True}],
        response_mappings=[{"variable_name": "next_slot", "json_path": "data.slots[0].time"}],
    )
    inline = check(
        await client.post(
            "/v1/tools/test-run",
            json={"tool": body, "arguments": {"date": "2026-10-20"}},
            headers=account.headers,
        )
    ).json()
    assert inline["is_error"] is False and inline["http_status"] == 200
    assert inline["mapped_variables"] == {"next_slot": "10:00"}
    assert inline["request"]["headers"]["X-Api-Key"] == "****4321"
    assert upstream[-1].headers["X-Api-Key"] == "secret-value-4321"
    assert json.loads(upstream[-1].content) == {"date": "2026-10-20"}
    tool = await make(client, account, body)
    saved = check(
        await client.post(
            "/v1/tools/test-run",
            json={"tool_id": tool["id"], "arguments": {"date": "x"}},
            headers=account.headers,
        )
    ).json()
    assert saved["is_error"] is False and upstream[-1].headers["X-Api-Key"] == "secret-value-4321"
    assert "secret-value" not in json.dumps(saved)


async def test_test_run_blocks_private_and_rejects_other_types(
    client: httpx.AsyncClient, account: Account, upstream: list[httpx.Request]
) -> None:
    blocked = check(
        await client.post(
            "/v1/tools/test-run",
            json={"tool": http_tool(url="https://internal.example.com/x"), "arguments": {}},
            headers=account.headers,
        )
    ).json()
    assert blocked["is_error"] and blocked["error_code"] == "blocked_address" and upstream == []
    wrong = check(
        await client.post(
            "/v1/tools/test-run", json={"tool": end_call(), "arguments": {}}, headers=account.headers
        )
    )
    assert wrong.status_code == 422


async def test_test_run_rate_limit(
    client: httpx.AsyncClient, app: FastAPI, upstream: list[httpx.Request]
) -> None:
    account = await signup(client, app)
    request = {"tool": http_tool(), "arguments": {"date": "d"}}
    statuses = [
        (await client.post("/v1/tools/test-run", json=request, headers=account.headers)).status_code
        for _ in range(31)
    ]
    assert statuses[:30] == [200] * 30
    limited = check(await client.post("/v1/tools/test-run", json=request, headers=account.headers))
    assert limited.status_code == 429


# Internal tool secrets ------------------------------------------------------------------------


async def test_internal_tool_secrets(client: httpx.AsyncClient, account: Account, app: FastAPI) -> None:
    from tests.runtime_support import insert_call, owner_sql

    body = http_tool(headers=[{"name": "Authorization", "value": "Bearer abcdefgh1234", "secret": True}])
    tool = await make(client, account, body)
    agent = await create_ok(client, account)
    await client.put(
        f"/v1/agents/{agent['id']}/tools", json={"tool_ids": [tool["id"]]}, headers=account.headers
    )
    detail = (await client.get(f"/v1/agents/{agent['id']}", headers=account.headers)).json()
    version_id = detail["draft_version"]["id"]
    call_id = insert_call(account.workspace_id, status="in_progress")
    owner_sql(
        "update calls set agent_id = %s, agent_version_id = %s where id = %s",
        (agent["id"], version_id, call_id),
    )
    token = app.state.settings.service_token.get_secret_value()
    service = {"Authorization": f"Bearer {token}"}
    got = check(await client.get(f"/v1/internal/calls/{call_id}/tool-secrets", headers=service))
    assert got.status_code == 200 and list(got.json()["secrets"].values()) == ["Bearer abcdefgh1234"]
    hidden = check(await client.get(f"/v1/internal/calls/{call_id}/tool-secrets", headers=account.headers))
    assert hidden.status_code == 404
    closed = insert_call(account.workspace_id, status="ended")
    refused = check(await client.get(f"/v1/internal/calls/{closed}/tool-secrets", headers=service))
    assert refused.status_code == 409


@pytest.mark.parametrize("path", ["/v1/tools/presets", "/v1/tools"])
async def test_requires_sign_in(client: httpx.AsyncClient, path: str) -> None:
    assert (await client.get(path)).status_code == 401
