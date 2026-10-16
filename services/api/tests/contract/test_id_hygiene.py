"""Id and error hygiene sweep (T092, FR-019).

For every assembled path with an ``{..._id}`` parameter, a malformed id and an unknown
well-formed id both return a 404 problem. Internal faults return a generic 500 with a
``trace_id`` and no exception text. The sweep grows automatically as features add paths.
"""

from __future__ import annotations

import re
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from tests.conftest import Account
from tests.contract.conftest import check, contract_dict

PREFIX_FOR_PARAM = {
    "transaction_id": "txn",
    "call_id": "call",
    "agent_id": "agt",
    "version_id": "agv",
    "workspace_id": "ws",
}
WELL_FORMED_ULID = "01ARZ3NDEKTSV4RRFFQ69G5FAV"


def _id_paths() -> list[tuple[str, str]]:
    paths: dict[str, Any] = contract_dict()["paths"]  # type: ignore[assignment]
    out = []
    for path, item in paths.items():
        if "{" not in path or "get" not in item:
            continue
        out.append(("get", path))
    return out


def _fill(path: str, malformed: bool) -> str:
    def repl(match: re.Match[str]) -> str:
        name = match.group(1)
        if malformed:
            return "not-an-id"
        prefix = PREFIX_FOR_PARAM.get(name, name.removesuffix("_id"))
        return f"{prefix}_{WELL_FORMED_ULID}"

    return "/v1" + re.sub(r"\{([a-z_]+)\}", repl, path)


def test_sweep_has_paths() -> None:
    assert ("get", "/billing/transactions/{transaction_id}") in _id_paths()


@pytest.mark.parametrize(("method", "path"), _id_paths())
@pytest.mark.parametrize("malformed", [True, False], ids=["malformed", "unknown"])
async def test_bad_ids_are_404(
    client: httpx.AsyncClient, account: Account, method: str, path: str, malformed: bool
) -> None:
    response = check(await client.request(method, _fill(path, malformed), headers=account.headers))
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["code"] == "not_found"


async def test_unknown_route_is_a_404_problem(client: httpx.AsyncClient, account: Account) -> None:
    response = await client.get("/v1/agents/not-an-id", headers=account.headers)
    assert response.status_code == 404
    assert response.json()["code"] == "not_found"


async def test_internal_fault_is_generic_500_with_trace_id(
    client: httpx.AsyncClient, account: Account, app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.billing import service

    async def explode(*args: object, **kwargs: object) -> None:
        raise RuntimeError('relation "credit_transactions" does not exist; password=hunter2')

    monkeypatch.setattr(service, "latest_seq_and_balance", explode)
    response = await client.get("/v1/billing/balance", headers=account.headers)
    assert response.status_code == 500
    body = response.json()
    assert re.fullmatch(r"[0-9a-f]{32}", body["trace_id"])
    assert body["code"] == "internal_error"
    assert "credit_transactions" not in response.text and "hunter2" not in response.text
    assert "Traceback" not in response.text
