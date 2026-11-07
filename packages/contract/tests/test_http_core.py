"""The HTTP tool core driven by the shared vectors (005 T035, T036), and its redirect rules."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest

from callwright_contract import http_core

VECTORS: dict[str, Any] = json.loads((Path(__file__).with_name("http_exec_vectors.json")).read_text())


@pytest.mark.parametrize("case", VECTORS["requests"], ids=lambda c: c["name"])
def test_request_vectors(case: dict[str, Any]) -> None:
    prepared = http_core.prepare_request(
        case["spec"],
        case["arguments"],
        case.get("dynamic"),
        case.get("mapped"),
        case.get("secrets"),
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


def test_error_payload() -> None:
    assert http_core.error_payload("timeout", "No answer.") == '{"error":"timeout","message":"No answer."}'
    assert json.loads(http_core.error_payload("http_status", "HTTP 500.", 500))["http_status"] == 500


@pytest.mark.parametrize(
    ("status", "method", "expect"),
    [
        (303, "PUT", "GET"),
        (301, "POST", "GET"),
        (302, "PATCH", "GET"),
        (302, "GET", "GET"),
        (301, "DELETE", "DELETE"),
        (307, "POST", "POST"),
        (308, "PUT", "PUT"),
    ],
)
def test_redirect_method(status: int, method: str, expect: str) -> None:
    method_after, content = http_core.redirected(status, method, b"{}")
    assert method_after == expect
    assert (content is None) == (expect != method)


def test_timeout_and_blocked_codes() -> None:
    assert http_core.timeout_s({}) == 8.0
    assert http_core.timeout_s({"timeout_ms": 2500}) == 2.5
    assert http_core.blocked_error_code("private_address") == "blocked_address"
    assert http_core.blocked_error_code("https_required") == "blocked_address"
    assert http_core.blocked_error_code("dns_failure") == "connection_error"


async def test_read_capped() -> None:
    async def chunks(n: int) -> AsyncIterator[bytes]:
        for _ in range(n):
            yield b"x" * 1024

    assert await http_core.read_capped(chunks(2)) == (b"x" * 2048, False)
    body, cut = await http_core.read_capped(chunks(70))
    assert cut and len(body) == http_core.MAX_RESPONSE_BYTES
