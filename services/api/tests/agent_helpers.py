"""Helpers for agent builder tests (002)."""

from __future__ import annotations

import copy
from typing import Any

import httpx

from app.agents.defaults import default_config
from tests.conftest import Account

PROMPT = "You answer calls for a dental clinic."


def blank_config(agent_type: str = "single_prompt", **changes: Any) -> dict[str, Any]:
    cfg = default_config(agent_type)
    cfg["prompt"] = PROMPT
    cfg.update(copy.deepcopy(changes))
    return cfg


async def create(
    client: httpx.AsyncClient,
    account: Account,
    *,
    name: str = "Clinic desk",
    agent_type: str = "single_prompt",
    config: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    **body: Any,
) -> httpx.Response:
    payload: dict[str, Any] = {"name": name, "type": agent_type, **body}
    if config is not None or "template_id" not in body:
        payload["config"] = config if config is not None else {"prompt": PROMPT}
    return await client.post("/v1/agents", json=payload, headers={**account.headers, **(headers or {})})


async def create_ok(client: httpx.AsyncClient, account: Account, **kwargs: Any) -> dict[str, Any]:
    response = await create(client, account, **kwargs)
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


async def save(
    client: httpx.AsyncClient,
    account: Account,
    agent: dict[str, Any],
    config: dict[str, Any],
    *,
    revision: int | None = None,
    **body: Any,
) -> httpx.Response:
    rev = agent["draft_revision"] if revision is None else revision
    return await client.put(
        f"/v1/agents/{agent['id']}/draft",
        json={"config": config, **body},
        headers={**account.headers, "If-Match": f'"{rev}"'},
    )


async def save_prompt(
    client: httpx.AsyncClient, account: Account, agent: dict[str, Any], prompt: str
) -> dict[str, Any]:
    config = copy.deepcopy(agent["draft_config"])
    config["prompt"] = prompt
    response = await save(client, account, agent, config)
    assert response.status_code == 200, response.text
    result: dict[str, Any] = response.json()
    return result
