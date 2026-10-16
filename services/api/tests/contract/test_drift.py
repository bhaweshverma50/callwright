"""Drift between the served API and the assembled contract (T023, Principle VII).

Compares ``(method, path, status)`` triples from ``app.openapi()`` with contracts/openapi.yaml.
Two FastAPI artefacts are ignored: the automatic 422 FastAPI adds to every route with inputs
(the contract lists 422 only where callers are expected to handle it), and dev-only routes,
which are excluded from the schema.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI

from tests.contract.conftest import contract_dict

METHODS = {"get", "post", "put", "patch", "delete"}


def _triples(paths: dict[str, Any], strip_prefix: str = "") -> set[tuple[str, str, str]]:
    out: set[tuple[str, str, str]] = set()
    for path, item in paths.items():
        local = path[len(strip_prefix) :] if strip_prefix and path.startswith(strip_prefix) else path
        for method, op in item.items():
            if method not in METHODS:
                continue
            for status in op.get("responses", {}):
                out.add((method, local, str(status)))
    return out


def test_operations_match(app: FastAPI) -> None:
    served = {(m, p) for m, p, _ in _triples(app.openapi()["paths"], "/v1")}
    documented = {(m, p) for m, p, _ in _triples(contract_dict()["paths"])}  # type: ignore[arg-type]
    assert served - documented == set(), "routes served but not in the contract"
    assert documented - served == set(), "contract operations the API does not serve"


def test_statuses_match(app: FastAPI) -> None:
    documented = _triples(contract_dict()["paths"])  # type: ignore[arg-type]
    served = _triples(app.openapi()["paths"], "/v1")
    auto_422 = {(m, p, s) for m, p, s in served - documented if s == "422"}
    assert served - documented - auto_422 == set(), "statuses served but not documented"
    assert documented - served == set(), "documented statuses the route does not declare"
