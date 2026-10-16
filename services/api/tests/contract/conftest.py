"""Contract test harness (T022): validate live responses against contracts/openapi.yaml.

``check(response)`` validates an ``httpx.Response`` from the ASGI app with openapi-core: the
status must be declared for the operation and the body and declared headers must match.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

import httpx
import pytest
import yaml
from openapi_core import Config, OpenAPI
from openapi_core.testing import MockRequest, MockResponse

CONTRACT = Path(__file__).resolve().parents[4] / "contracts" / "openapi.yaml"


@lru_cache(maxsize=1)
def contract() -> OpenAPI:
    config = Config(extra_media_type_deserializers={"application/problem+json": json.loads})
    return OpenAPI.from_file_path(str(CONTRACT), config=config)


@lru_cache(maxsize=1)
def contract_dict() -> dict[str, object]:
    loaded: dict[str, object] = yaml.safe_load(CONTRACT.read_text())
    return loaded


def check(response: httpx.Response) -> httpx.Response:
    request = response.request
    content_type = response.headers.get("content-type", "application/json").split(";")[0]
    mock_request = MockRequest(
        "http://testserver",
        request.method.lower(),
        request.url.path,
        args=dict(request.url.params),
        headers=dict(request.headers),
        data=request.content,
        content_type=request.headers.get("content-type", "application/json").split(";")[0],
    )
    mock_response = MockResponse(
        response.content,
        status_code=response.status_code,
        headers=dict(response.headers),
        content_type=content_type,
    )
    try:
        contract().validate_response(mock_request, mock_response)
    except Exception as exc:  # pragma: no cover - failure path
        pytest.fail(
            f"{request.method} {request.url.path} -> {response.status_code} breaks the contract: "
            f"{exc!r} / {exc.__cause__!r}\nbody: {response.text[:500]}"
        )
    return response
