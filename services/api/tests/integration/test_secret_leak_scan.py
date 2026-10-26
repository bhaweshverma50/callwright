"""Secret leak scan (005 T090, SC-005): a canary secret header value never appears in API
responses, version snapshots, test-run output or captured logs."""

from __future__ import annotations

import logging

import httpx
import pytest
from fastapi import FastAPI

from tests.agent_helpers import create_ok
from tests.conftest import Account
from tests.contract.test_tools_contract import http_tool, make, upstream  # noqa: F401

CANARY = "canary-SECRET-7d1f9e2b"


async def test_canary_never_leaks(
    client: httpx.AsyncClient,
    account: Account,
    app: FastAPI,
    upstream: list[httpx.Request],  # noqa: F811
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    bodies: list[str] = []

    def keep(response: httpx.Response) -> httpx.Response:
        bodies.append(response.text)
        return response

    tool = await make(
        client,
        account,
        http_tool(headers=[{"name": "Authorization", "value": f"Bearer {CANARY}", "secret": True}]),
    )
    bodies.append(str(tool))
    keep(await client.get(f"/v1/tools/{tool['id']}", headers=account.headers))
    keep(await client.get("/v1/tools", headers=account.headers))
    keep(await client.post(f"/v1/tools/{tool['id']}/duplicate", headers=account.headers))
    keep(
        await client.post(
            "/v1/tools/test-run",
            json={"tool_id": tool["id"], "arguments": {"date": "d"}},
            headers=account.headers,
        )
    )
    agent = await create_ok(client, account)
    keep(
        await client.put(
            f"/v1/agents/{agent['id']}/tools", json={"tool_ids": [tool["id"]]}, headers=account.headers
        )
    )
    detail = keep(await client.get(f"/v1/agents/{agent['id']}", headers=account.headers)).json()
    keep(
        await client.get(
            f"/v1/agents/{agent['id']}/versions/{detail['draft_version']['id']}", headers=account.headers
        )
    )
    assert upstream and upstream[-1].headers["authorization"] == f"Bearer {CANARY}", "the secret is used"
    for body in bodies:
        assert CANARY not in body
    assert CANARY not in caplog.text
