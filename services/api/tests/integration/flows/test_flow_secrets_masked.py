"""Webhook secrets never appear unmasked (004 T096): not in the flow, the compile preview, the
published version, nor its compiled form; the worker reaches them by reference."""

from __future__ import annotations

import json

import httpx

from app.tools.service import secret_refs
from tests.conftest import Account
from tests.flow_helpers import clinic, create_flow, save

SECRET = "sk-live-9f8e7d6c5b4a"


async def test_secret_stays_a_reference_everywhere(client: httpx.AsyncClient, account: Account) -> None:
    flow = (await create_flow(client, account))["flow"]
    g = clinic()
    g["nodes"][3]["config"]["request"]["headers"].append(
        {"name": "Authorization", "value": f"Bearer {SECRET}", "secret": True}
    )
    saved = await save(client, account, flow, g)
    assert saved.status_code == 200 and SECRET not in saved.text
    loaded = await client.get(f"/v1/flows/{flow['id']}", headers=account.headers)
    assert SECRET not in loaded.text
    preview = await client.post(f"/v1/flows/{flow['id']}/compile", headers=account.headers)
    assert SECRET not in preview.text
    published = await client.post(
        f"/v1/flows/{flow['id']}/publish", json={"expected_revision": 2}, headers=account.headers
    )
    assert published.status_code == 201, published.text
    version = await client.get(
        f"/v1/agents/{flow['agent_id']}/versions/{published.json()['agent_version_id']}",
        headers=account.headers,
    )
    assert SECRET not in version.text
    refs = secret_refs(version.json()["config"])
    assert len(refs) == 1 and refs[0].startswith("flow_hdr:")
    assert SECRET not in json.dumps(version.json())
