"""contracts/flows.yaml: POST /flows/{flow_id}/assistant 200, 402, 409, 504 (004 T084)."""

from __future__ import annotations

import httpx
from fastapi import FastAPI

from tests.conftest import Account, signup
from tests.contract.conftest import check
from tests.contract.test_prompt_ai_contract import drain
from tests.flow_helpers import create_flow


def _ask(text: str, revision: int = 1) -> dict[str, object]:
    return {"messages": [{"role": "user", "content": text}], "base_revision": revision}


async def test_shapes(client: httpx.AsyncClient, app: FastAPI, account: Account) -> None:
    flow = (await create_flow(client, account))["flow"]
    url = f"/v1/flows/{flow['id']}/assistant"
    ok = check(
        await client.post(
            url, json=_ask("Add a step that collects the date of birth"), headers=account.headers
        )
    )
    assert ok.status_code == 200
    assert (
        check(await client.post(url, json=_ask("hi", revision=5), headers=account.headers)).status_code == 409
    )
    assert (
        check(await client.post(url, json=_ask("hi [timeout]"), headers=account.headers)).status_code == 504
    )
    broke = await signup(client, app)
    broke_flow = (await create_flow(client, broke))["flow"]
    await drain(app, broke)
    refused = check(
        await client.post(f"/v1/flows/{broke_flow['id']}/assistant", json=_ask("hi"), headers=broke.headers)
    )
    assert refused.status_code == 402
