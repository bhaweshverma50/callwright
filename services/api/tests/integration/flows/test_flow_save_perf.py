"""Save and validate at 200 nodes (004 T095, plan performance goals): p95 under 300 ms."""

from __future__ import annotations

import time

import httpx

from app.flows.starter import config_with_defaults
from tests.conftest import Account
from tests.flow_helpers import create_flow


def big_graph() -> dict[str, object]:
    nodes = [
        {
            "id": "n_start000",
            "type": "start",
            "label": "Start",
            "position": {"x": 0, "y": 0},
            "config": config_with_defaults("start", {}),
        }
    ]
    edges = []
    prev = "n_start000"
    for i in range(198):
        nid = f"n_s{i:07d}"
        nodes.append(
            {
                "id": nid,
                "type": "say",
                "label": f"Step {i}",
                "position": {"x": 300 * (i + 1), "y": 0},
                "config": {"message": f"Line {i}", "allow_interruptions": True},
            }
        )
        edges.append(
            {"id": f"e_s{i:07d}", "source": prev, "target": nid, "trigger": "always", "sort_order": 0}
        )
        prev = nid
    nodes.append(
        {
            "id": "n_end00000",
            "type": "end",
            "label": "End",
            "position": {"x": 0, "y": 300},
            "config": config_with_defaults("end", {}),
        }
    )
    edges.append(
        {"id": "e_last0000", "source": prev, "target": "n_end00000", "trigger": "always", "sort_order": 0}
    )
    return {"nodes": nodes, "edges": edges, "viewport": {"x": 0, "y": 0, "zoom": 1}}


def p95(values: list[float]) -> float:
    ordered = sorted(values)
    return ordered[max(0, int(len(ordered) * 0.95) - 1)]


async def test_save_and_validate_p95(client: httpx.AsyncClient, account: Account) -> None:
    flow = (await create_flow(client, account))["flow"]
    graph = big_graph()
    saves: list[float] = []
    checks: list[float] = []
    revision = flow["revision"]
    for _ in range(12):
        started = time.perf_counter()
        r = await client.put(
            f"/v1/flows/{flow['id']}",
            json={"name": "Big flow", "graph": graph},
            headers={**account.headers, "If-Match": f'"{revision}"'},
        )
        saves.append((time.perf_counter() - started) * 1000)
        assert r.status_code == 200, r.text
        revision = r.json()["revision"]
        assert r.json()["last_validation"]["errors"] == 0
        started = time.perf_counter()
        v = await client.post(
            f"/v1/flows/{flow['id']}/validate", json={"graph": graph}, headers=account.headers
        )
        checks.append((time.perf_counter() - started) * 1000)
        assert v.status_code == 200
    assert p95(saves) < 300, saves
    assert p95(checks) < 300, checks
