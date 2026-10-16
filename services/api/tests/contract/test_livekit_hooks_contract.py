"""POST /v1/livekit/webhook against contracts/livekit_hooks.yaml (003 T073)."""

from __future__ import annotations

import json
from typing import Any

import httpx
from fastapi import FastAPI

from app.core.livekit import sign_webhook
from tests.contract.conftest import check
from tests.runtime_support import Runtime

URL = "/v1/livekit/webhook"


def signed(app: FastAPI, event: dict[str, Any]) -> tuple[bytes, dict[str, str]]:
    body = json.dumps(event)
    settings = app.state.settings
    token = sign_webhook(
        settings.livekit_api_key.get_secret_value(), settings.livekit_api_secret.get_secret_value(), body
    )
    return body.encode(), {"Authorization": token, "Content-Type": "application/webhook+json"}


async def test_200_for_handled_and_unknown_events(
    app: FastAPI, client: httpx.AsyncClient, runtime: Runtime
) -> None:
    for event in (
        {"event": "room_finished", "id": "EV_1", "createdAt": 1760600000, "room": {"name": "call-unknown"}},
        {
            "event": "participant_left",
            "id": "EV_2",
            "createdAt": "1760600000",
            "participant": {"identity": "web-x"},
        },
        {"event": "track_published", "id": "EV_3", "createdAt": 1760600000},
        {
            "event": "egress_ended",
            "id": "EV_4",
            "createdAt": 1760600000,
            "egressInfo": {"egressId": "EG_unknown", "roomName": "nope", "status": "EGRESS_COMPLETE"},
        },
    ):
        body, headers = signed(app, event)
        response = check(await client.post(URL, content=body, headers=headers))
        assert response.status_code == 200, event


async def test_401_for_bad_signature_or_body_hash(
    app: FastAPI, client: httpx.AsyncClient, runtime: Runtime
) -> None:
    body, headers = signed(app, {"event": "room_finished", "id": "EV_5", "createdAt": 1})
    tampered = body.replace(b"room_finished", b"room_started_")
    assert check(await client.post(URL, content=tampered, headers=headers)).status_code == 401
    assert (
        check(await client.post(URL, content=body, headers={"Content-Type": "application/json"})).status_code
        == 401
    )
    forged = {"Authorization": "Bearer not.a.jwt", "Content-Type": "application/json"}
    assert check(await client.post(URL, content=body, headers=forged)).status_code == 401
