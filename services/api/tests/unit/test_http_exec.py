"""HTTP tool core driven by the shared vectors (005 T035, T036)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from app.tools import http_core

HERE = Path(__file__).resolve().parent
VECTORS: dict[str, Any] = json.loads((HERE / "fixtures" / "http_exec_vectors.json").read_text())
WORKER_COPY = HERE.parents[2] / "voice-worker" / "tests" / "unit" / "fixtures" / "http_exec_vectors.json"


@pytest.mark.skipif(not WORKER_COPY.exists(), reason="voice worker sources not present")
def test_worker_copy_matches() -> None:
    assert WORKER_COPY.read_text() == (HERE / "fixtures" / "http_exec_vectors.json").read_text()


@pytest.mark.parametrize("case", VECTORS["requests"], ids=lambda c: c["name"])
def test_request_vectors(case: dict[str, Any]) -> None:
    prepared = http_core.prepare_request(
        case["spec"], case["arguments"], case.get("dynamic"), case.get("mapped"), case.get("secrets")
    )
    expect = case["expect"]
    assert prepared.method == expect["method"]
    assert prepared.url == expect["url"]
    assert prepared.body == expect["body"]
    assert prepared.headers == expect["headers"]
    assert prepared.missing_variables == expect["missing"]


@pytest.mark.parametrize("case", VECTORS["mappings"], ids=lambda c: c["name"])
def test_mapping_vectors(case: dict[str, Any]) -> None:
    mapped, missing = http_core.apply_mappings(case["body"], case["mappings"])
    assert mapped == case["expect"]["mapped"]
    assert missing == case["expect"]["missing"]


@pytest.mark.parametrize("case", VECTORS["payloads"], ids=lambda c: c["name"])
def test_payload_vectors(case: dict[str, Any]) -> None:
    if "body_repeat" in case:
        body = case["body_repeat"]["text"] * case["body_repeat"]["times"]
        payload = http_core.success_payload(body)
        assert len(payload) == case["expect_length"] and payload.endswith(case["expect_suffix"])
    else:
        assert http_core.success_payload(case["body"]) == case["expect"]


def test_scrub_masks_secret_values() -> None:
    assert http_core.scrub("token=abcd1234 ok", ["abcd1234"]) == "token=**** ok"
