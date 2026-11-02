"""Contract tests for contracts/test_runs.yaml (008 T021), internal endpoints included."""

from __future__ import annotations

import httpx

from tests.conftest import Account
from tests.contract.conftest import check
from tests.runtime_support import SERVICE_HEADERS, idem
from tests.sim_support import SimEnv, make_agent

TRN = "trn_01ARZ3NDEKTSV4RRFFQ69G5FAV"


async def test_every_test_run_operation(sim_env: SimEnv, client: httpx.AsyncClient, account: Account) -> None:
    h = account.headers
    agent = await make_agent(client, account)
    a = agent.agent_id
    rows = [{"user_prompt": f"Q{i}", "expected_behaviour": "Answers."} for i in range(2)]
    await client.post("/v1/test-cases/import", json={"agent_id": a, "test_cases": rows}, headers=h)
    assert (
        check(
            await client.post(
                "/v1/test-runs", json={"agent_id": a, "judge_model": "x/y"}, headers={**h, **idem()}
            )
        ).status_code
        == 422
    )
    run = check(await client.post("/v1/test-runs", json={"agent_id": a}, headers={**h, **idem()}))
    assert run.status_code == 202
    trn = run.json()["test_run_id"]
    check(await client.get(f"/v1/test-runs?agent_id={a}", headers=h))
    detail = check(await client.get(f"/v1/test-runs/{trn}", headers=h)).json()
    case_id = detail["results"][0]["test_case_id"]
    early = await client.patch(
        f"/v1/test-runs/{trn}/results/{case_id}", json={"override_status": "passed"}, headers=h
    )
    assert check(early).status_code == 409

    await sim_env.run_api_jobs()
    base = f"/v1/internal/test-runs/{trn}/cases/{case_id}"
    spec = check(await client.get(f"{base}/spec", headers=SERVICE_HEADERS))
    assert spec.json()["agent_type"] == "single_prompt" and spec.json()["user_prompt"] == "Q0"
    result = await client.post(
        f"{base}/result",
        json={
            "status": "completed",
            "agent_response": "Sure.",
            "tool_calls": [
                {"name": "lookup", "arguments": {"q": 1}, "output": "{}", "answer_source": "mock"},
                {"name": "end_call", "arguments": {}, "output": None, "answer_source": None},
            ],
            "usage": {},
            "duration_ms": 10,
        },
        headers=SERVICE_HEADERS,
    )
    assert check(result).status_code == 204
    await sim_env.drain()
    done = check(await client.get(f"/v1/test-runs/{trn}", headers=h)).json()
    assert done["status"] == "completed"
    assert check(await client.get(f"{base}/spec", headers=SERVICE_HEADERS)).status_code == 409
    over = await client.patch(
        f"/v1/test-runs/{trn}/results/{case_id}", json={"override_status": "failed"}, headers=h
    )
    assert check(over).status_code == 200
    missing = await client.patch(
        f"/v1/test-runs/{trn}/results/tc_01ARZ3NDEKTSV4RRFFQ69G5FAV",
        json={"override_status": None},
        headers=h,
    )
    assert check(missing).status_code == 404
    check(await client.get(f"/v1/test-runs/{trn}/export", headers=h))
    assert check(await client.post(f"/v1/test-runs/{trn}/cancel", headers=h)).status_code == 409
    assert check(await client.post(f"/v1/test-runs/{TRN}/cancel", headers=h)).status_code == 404
    assert check(await client.get(f"/v1/test-runs/{TRN}/export", headers=h)).status_code == 404
    gone = f"/v1/internal/test-runs/{TRN}/cases/{case_id}"
    assert check(await client.get(f"{gone}/spec", headers=SERVICE_HEADERS)).status_code == 404
    lost = await client.post(f"{gone}/result", json={"status": "error"}, headers=SERVICE_HEADERS)
    assert check(lost).status_code == 404

    second = check(await client.post("/v1/test-runs", json={"agent_id": a}, headers={**h, **idem()})).json()
    assert (
        check(await client.post(f"/v1/test-runs/{second['test_run_id']}/cancel", headers=h)).status_code
        == 200
    )

    empty = await make_agent(client, account)
    refused = await client.post("/v1/test-runs", json={"agent_id": empty.agent_id}, headers={**h, **idem()})
    assert check(refused).status_code == 409
