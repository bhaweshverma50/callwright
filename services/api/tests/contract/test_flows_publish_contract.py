"""contracts/flows.yaml: validate, compile and publish (004 T032)."""

from __future__ import annotations

import httpx

from tests.conftest import Account
from tests.contract.conftest import check
from tests.flow_helpers import clinic, create_flow, save


async def test_validate_compile_publish(client: httpx.AsyncClient, account: Account) -> None:
    flow = (await create_flow(client, account))["flow"]
    base = f"/v1/flows/{flow['id']}"
    assert check(await client.post(f"{base}/validate", headers=account.headers)).status_code == 200
    assert (
        check(
            await client.post(f"{base}/validate", json={"graph": clinic()}, headers=account.headers)
        ).status_code
        == 200
    )
    assert check(await client.post(f"{base}/compile", headers=account.headers)).status_code == 200
    published = check(
        await client.post(
            f"{base}/publish", json={"expected_revision": 1, "release_notes": "v1"}, headers=account.headers
        )
    )
    assert published.status_code == 201


async def test_publish_errors(client: httpx.AsyncClient, account: Account) -> None:
    flow = (await create_flow(client, account))["flow"]
    base = f"/v1/flows/{flow['id']}"
    g = clinic()
    g["nodes"][4]["config"]["message"] = ""
    await save(client, account, flow, g)
    compiled = check(await client.post(f"{base}/compile", headers=account.headers))
    assert compiled.json()["ok"] is False and compiled.json()["compiled"] is None
    assert (
        check(
            await client.post(f"{base}/publish", json={"expected_revision": 2}, headers=account.headers)
        ).status_code
        == 422
    )
    assert (
        check(
            await client.post(f"{base}/publish", json={"expected_revision": 1}, headers=account.headers)
        ).status_code
        == 409
    )
