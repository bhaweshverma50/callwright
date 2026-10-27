"""Contract tests for analysis variables and call analysis (007 T013, T014 database half)."""

from __future__ import annotations

import httpx

from tests.conftest import Account
from tests.contract.conftest import check
from tests.fakes.fake_llm import FakeLlm
from tests.quality_support import scripted_call
from tests.runtime_support import Runtime, idem


async def _agent(runtime: Runtime, account: Account) -> str:
    return runtime.versions.add_agent(account.workspace_id).agent_id


async def test_crud_order_and_delete(client: httpx.AsyncClient, account: Account, runtime: Runtime) -> None:
    h = account.headers
    agent = await _agent(runtime, account)
    url = f"/v1/agents/{agent}/analysis-variables"
    a = check(
        await client.post(
            url, json={"name": "appointment_booked", "type": "boolean", "description": "Booked?"}, headers=h
        )
    )
    assert a.status_code == 201 and a.json()["position"] == 0 and a.json()["choices"] is None
    b = check(
        await client.post(
            url,
            json={
                "name": "preferred_day",
                "type": "choice",
                "description": "Day",
                "choices": ["Monday", "Tuesday"],
            },
            headers=h,
        )
    )
    assert b.status_code == 201
    listed = check(await client.get(url, headers=h)).json()["items"]
    assert [v["name"] for v in listed] == ["appointment_booked", "preferred_day"]
    order = [b.json()["id"], a.json()["id"]]
    assert check(await client.put(f"{url}/order", json={"variable_ids": order}, headers=h)).status_code == 204
    assert [v["id"] for v in check(await client.get(url, headers=h)).json()["items"]] == order
    bad_order = check(await client.put(f"{url}/order", json={"variable_ids": order[:1]}, headers=h))
    assert bad_order.status_code == 422
    patched = check(
        await client.patch(
            f"/v1/analysis-variables/{a.json()['id']}", json={"description": "Slot confirmed"}, headers=h
        )
    )
    assert patched.status_code == 200 and patched.json()["description"] == "Slot confirmed"
    to_text = check(
        await client.patch(f"/v1/analysis-variables/{b.json()['id']}", json={"type": "string"}, headers=h)
    )
    assert to_text.status_code == 200 and to_text.json()["choices"] is None
    assert (
        check(await client.delete(f"/v1/analysis-variables/{a.json()['id']}", headers=h)).status_code == 204
    )
    assert (
        check(await client.delete(f"/v1/analysis-variables/{a.json()['id']}", headers=h)).status_code == 404
    )
    # A deleted name can be used again.
    again = check(
        await client.post(
            url, json={"name": "appointment_booked", "type": "boolean", "description": "x"}, headers=h
        )
    )
    assert again.status_code == 201


async def test_validation_uniqueness_and_limit(
    client: httpx.AsyncClient, account: Account, runtime: Runtime
) -> None:
    h = account.headers
    url = f"/v1/agents/{await _agent(runtime, account)}/analysis-variables"
    bad = check(
        await client.post(
            url, json={"name": "Preferred Day", "type": "string", "description": "x"}, headers=h
        )
    )
    assert bad.status_code == 422
    assert (
        bad.json()["errors"][0]["message"]
        == "Use lowercase letters, digits and underscores, starting with a letter"
    )
    extra = check(
        await client.post(
            url, json={"name": "mood", "type": "string", "description": "x", "choices": ["a", "b"]}, headers=h
        )
    )
    assert extra.status_code == 422 and extra.json()["errors"][0]["pointer"] == "/choices"
    one_choice = check(
        await client.post(
            url, json={"name": "day", "type": "choice", "description": "x", "choices": ["Mon"]}, headers=h
        )
    )
    assert one_choice.status_code == 422
    assert (
        check(
            await client.post(url, json={"name": "v0", "type": "string", "description": "x"}, headers=h)
        ).status_code
        == 201
    )
    dup = check(await client.post(url, json={"name": "v0", "type": "number", "description": "x"}, headers=h))
    assert dup.status_code == 409
    for i in range(1, 25):
        r = await client.post(url, json={"name": f"v{i}", "type": "string", "description": "x"}, headers=h)
        assert r.status_code == 201
    limit = check(
        await client.post(url, json={"name": "v25", "type": "string", "description": "x"}, headers=h)
    )
    assert limit.status_code == 409 and "25" in limit.json()["detail"]


async def test_unknown_agent_and_tenancy(
    client: httpx.AsyncClient, account: Account, runtime: Runtime
) -> None:
    from tests.conftest import signup

    other = await signup(client, runtime.app)
    url = f"/v1/agents/{await _agent(runtime, account)}/analysis-variables"
    assert check(await client.get(url, headers=other.headers)).status_code == 404
    created = check(
        await client.post(
            url, json={"name": "x", "type": "string", "description": "x"}, headers=account.headers
        )
    )
    var_id = created.json()["id"]
    assert (
        check(
            await client.patch(f"/v1/analysis-variables/{var_id}", json={"name": "y"}, headers=other.headers)
        ).status_code
        == 404
    )


async def test_call_analysis_and_rerun(
    client: httpx.AsyncClient, account: Account, runtime: Runtime, quality: FakeLlm
) -> None:
    h = account.headers
    names: dict[str, str] = {}

    async def prepare(ws: str, agent_id: str) -> None:
        r = await client.post(
            f"/v1/agents/{agent_id}/analysis-variables",
            json={"name": "appointment_booked", "type": "boolean", "description": "Booked"},
            headers=h,
        )
        names["id"] = r.json()["id"]

    call = await scripted_call(runtime, account.workspace_id, prepare=prepare)
    got = check(await client.get(f"/v1/calls/{call.call_id}/analysis", headers=h)).json()
    assert got["values"][0]["status"] == "current"
    # Renamed variables keep the old value labelled renamed; deleted ones are labelled deleted.
    await client.patch(f"/v1/analysis-variables/{names['id']}", json={"name": "booked"}, headers=h)
    got = check(await client.get(f"/v1/calls/{call.call_id}/analysis", headers=h)).json()
    assert got["values"][0] == {**got["values"][0], "name": "appointment_booked", "status": "renamed"}
    await client.delete(f"/v1/analysis-variables/{names['id']}", headers=h)
    got = check(await client.get(f"/v1/calls/{call.call_id}/analysis", headers=h)).json()
    assert got["values"][0]["status"] == "deleted"
    key = idem()
    first = check(await client.post(f"/v1/calls/{call.call_id}/analysis/rerun", headers={**h, **key}))
    assert first.status_code == 202 and first.json()["status"] == "running"
    replay = check(await client.post(f"/v1/calls/{call.call_id}/analysis/rerun", headers={**h, **key}))
    assert replay.status_code == 202 and replay.json() == first.json()
    busy = check(await client.post(f"/v1/calls/{call.call_id}/analysis/rerun", headers={**h, **idem()}))
    assert busy.status_code == 409
    await runtime.run_jobs("rerun_analysis")
    got = check(await client.get(f"/v1/calls/{call.call_id}/analysis", headers=h)).json()
    assert got["status"] == "completed" and got["values"] == []  # deleted variables are not extracted again
    assert (
        check(await client.get("/v1/calls/call_01ARZ3NDEKTSV4RRFFQ69G5FAV/analysis", headers=h)).status_code
        == 404
    )
