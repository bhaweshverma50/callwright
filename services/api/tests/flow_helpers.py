"""Graph builders and HTTP helpers for flow tests (004)."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import httpx

from app.flows.starter import config_with_defaults
from tests.conftest import Account

FIXTURES = Path(__file__).parent / "integration" / "flows" / "fixtures"


def node(
    nid: str, type_: str, label: str | None = None, x: float = 0, y: float = 0, **config: Any
) -> dict[str, Any]:
    return {
        "id": nid,
        "type": type_,
        "label": label or type_.replace("_", " ").title(),
        "position": {"x": x, "y": y},
        "config": config_with_defaults(type_, config),
    }


def edge(eid: str, source: str, target: str, trigger: str = "always", **kw: Any) -> dict[str, Any]:
    return {"id": eid, "source": source, "target": target, "trigger": trigger, "sort_order": 0, **kw}


def llm_edge(
    eid: str, source: str, target: str, label: str, condition: str = "When it fits", **kw: Any
) -> dict[str, Any]:
    return edge(eid, source, target, "llm_condition", label=label, condition=condition, **kw)


def graph(nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> dict[str, Any]:
    return {"nodes": nodes, "edges": edges, "viewport": {"x": 0, "y": 0, "zoom": 1}}


def basic() -> dict[str, Any]:
    """Start -> Agent -> End, valid with no issues."""
    return graph(
        [
            node("n_start000", "start", "Start"),
            node("n_agent000", "agent", "Triage", 300, instructions="Help the caller."),
            node("n_end00000", "end", "End", 600),
        ],
        [
            edge("e_start000", "n_start000", "n_agent000"),
            llm_edge("e_done0000", "n_agent000", "n_end00000", "Caller is done"),
        ],
    )


def clinic() -> dict[str, Any]:
    """The clinic v2 fixture: every node type, valid."""
    data: dict[str, Any] = json.loads((FIXTURES / "clinic_v2.json").read_text())
    return copy.deepcopy(data)


def codes(issues: list[dict[str, Any]], severity: str | None = None) -> list[str]:
    return [i["code"] for i in issues if severity is None or i["severity"] == severity]


async def create_flow(
    client: httpx.AsyncClient, account: Account, name: str = "Clinic intake", language: str = "en-GB"
) -> dict[str, Any]:
    response = await client.post(
        "/v1/flows", json={"name": name, "language": language}, headers=account.headers
    )
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


async def save(
    client: httpx.AsyncClient,
    account: Account,
    flow: dict[str, Any],
    graph_: dict[str, Any],
    *,
    revision: int | None = None,
    name: str | None = None,
    **extra: Any,
) -> httpx.Response:
    rev = flow["revision"] if revision is None else revision
    return await client.put(
        f"/v1/flows/{flow['id']}",
        json={"name": name or flow["name"], "graph": graph_, **extra},
        headers={**account.headers, "If-Match": f'"{rev}"'},
    )
