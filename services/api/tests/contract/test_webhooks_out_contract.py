"""/v1/webhooks/* and the ``webhooks`` payloads against contracts/webhooks_out.yaml (003 T084, T115)."""

from __future__ import annotations

import json
from typing import Any

import httpx
from fastapi import FastAPI
from openapi_schema_validator import OAS31Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from tests.conftest import Account
from tests.contract.conftest import check, contract_dict
from tests.contract.worker_compat import worker_client, worker_modules
from tests.runtime_support import Runtime, agent_config, dispatch_metadata, owner_sql, start_web_call

HOOK = "https://hooks.example.com/in"


def envelope_validator() -> OAS31Validator:
    resource = Resource.from_contents(contract_dict(), default_specification=DRAFT202012)
    registry: Registry[Any] = Registry().with_resource("urn:callwright", resource)
    return OAS31Validator({"$ref": "urn:callwright#/components/schemas/WebhookEnvelope"}, registry=registry)


async def _call_with_webhooks(
    app: FastAPI, client: httpx.AsyncClient, account: Account, runtime: Runtime, recording: str = "inherit"
) -> str:
    internal_api, metrics = worker_modules()
    agent = runtime.versions.add_agent(
        account.workspace_id, agent_config(advanced={"webhook_url": HOOK, "recording": recording})
    )
    started = await start_web_call(client, account.headers, agent.agent_id)
    call_id = str(started.json()["call_id"])
    api, _, http = worker_client(app)
    await api.claim(
        internal_api.ClaimRequest(
            job_id=f"AJ_{call_id[-8:]}",
            room_name=started.json()["room_name"],
            worker_id="AW",
            dispatch_metadata=dispatch_metadata(runtime, call_id),
        )
    )
    recorder = metrics.EventRecorder()
    recorder.status("in_progress")
    recorder.message("agent", "Hello", started_ms=0, ended_ms=500, turn_index=0)
    recorder.meters.add_tts("elevenlabs", "eleven_flash_v2_5", 5)
    poster = metrics.EventPoster(call_id, recorder, api, on_end_call=lambda reason: None)
    await poster.flush()
    recorder.status("ended", disconnect_reason="agent_hangup")
    await poster.stop()
    await runtime.run_jobs("run_pipeline")
    await http.aclose()
    return call_id


async def test_payloads_match_the_webhooks_schema(
    app: FastAPI, client: httpx.AsyncClient, account: Account, runtime: Runtime
) -> None:
    call_id = await _call_with_webhooks(app, client, account, runtime)
    rows = owner_sql(
        "select event, body from webhook_deliveries where call_id = %s order by created_at", (call_id,)
    )
    assert [r[0] for r in rows] == ["call_started", "call_ended", "call_analyzed"]
    validator = envelope_validator()
    for event, body in rows:
        payload = json.loads(body)
        validator.validate(payload)
        assert payload["event"] == event and payload["event_id"] == f"evt_{call_id}_{event}"
    analyzed = json.loads(rows[-1][1])["call"]
    assert analyzed["status"] == "completed" and analyzed["disconnect_reason"] == "agent_hangup"
    assert analyzed["transcript"]["items"][0]["text"] == "Hello"
    assert analyzed["cost"]["total_usd"] and analyzed["latency"] is not None
    assert analyzed["recording_enabled"] is True and analyzed["recording_url"] is None


async def test_not_recorded_call_payload(
    app: FastAPI, client: httpx.AsyncClient, account: Account, runtime: Runtime
) -> None:
    call_id = await _call_with_webhooks(app, client, account, runtime, recording="off")
    body = owner_sql(
        "select body from webhook_deliveries where call_id = %s and event = 'call_analyzed'", (call_id,)
    )
    call = json.loads(body[0][0])["call"]
    envelope_validator().validate(json.loads(body[0][0]))
    assert (call["recording_enabled"], call["recording_status"], call["recording_url"]) == (
        False,
        "not_recorded",
        None,
    )
    assert call["processing_warnings"] == []


async def test_signing_secret_endpoints(
    client: httpx.AsyncClient, account: Account, runtime: Runtime
) -> None:
    masked = check(await client.get("/v1/webhooks/signing-secret", headers=account.headers))
    assert masked.status_code == 200 and "secret" not in masked.json()
    rotated = check(await client.post("/v1/webhooks/signing-secret/rotate", headers=account.headers))
    assert rotated.status_code == 200
    body = rotated.json()
    assert body["secret"].startswith("whsec_") and body["secret_last4"] == body["secret"][-4:]
    assert body["previous_expires_at"] is not None
    after = check(await client.get("/v1/webhooks/signing-secret", headers=account.headers)).json()
    assert after["secret_last4"] == body["secret_last4"] and "secret" not in after
    for method, path in (
        ("GET", "/v1/webhooks/signing-secret"),
        ("POST", "/v1/webhooks/signing-secret/rotate"),
    ):
        assert check(await client.request(method, path)).status_code == 401


async def test_deliveries_list_detail_and_redeliver(
    app: FastAPI, client: httpx.AsyncClient, account: Account, runtime: Runtime
) -> None:
    call_id = await _call_with_webhooks(app, client, account, runtime)
    listed = check(await client.get(f"/v1/webhooks/deliveries?call_id={call_id}", headers=account.headers))
    assert listed.status_code == 200 and listed.json()["total"] == 3
    only = check(
        await client.get("/v1/webhooks/deliveries?event=call_analyzed&page_size=1", headers=account.headers)
    ).json()
    assert [i["event"] for i in only["items"]] == ["call_analyzed"]
    delivery_id = only["items"][0]["id"]
    detail = check(await client.get(f"/v1/webhooks/deliveries/{delivery_id}", headers=account.headers))
    assert detail.status_code == 200 and json.loads(detail.json()["body"])["event"] == "call_analyzed"
    redo = check(
        await client.post(f"/v1/webhooks/deliveries/{delivery_id}/redeliver", headers=account.headers)
    )
    assert redo.status_code == 202
    copy = redo.json()
    assert copy["redelivery_of"] == delivery_id and copy["status"] == "pending" and copy["id"] != delivery_id
    missing = "whd_01ARZ3NDEKTSV4RRFFQ69G5FAV"
    assert (
        check(await client.get(f"/v1/webhooks/deliveries/{missing}", headers=account.headers)).status_code
        == 404
    )
    assert (
        check(
            await client.post(f"/v1/webhooks/deliveries/{missing}/redeliver", headers=account.headers)
        ).status_code
        == 404
    )
    assert check(await client.get("/v1/webhooks/deliveries")).status_code == 401


async def test_send_test_event(
    app: FastAPI, client: httpx.AsyncClient, account: Account, runtime: Runtime
) -> None:
    received: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        received.append(request)
        return httpx.Response(204)

    original = app.state.webhook_http
    app.state.webhook_http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        ok = check(await client.post("/v1/webhooks/test", json={"url": HOOK}, headers=account.headers))
        assert ok.status_code == 200
        attempt = ok.json()
        assert attempt["n"] == 1 and attempt["status_code"] == 204 and attempt["error"] is None
        request = received[0]
        assert request.headers["Callwright-Event"] == "ping"
        assert request.headers["Callwright-Signature"].startswith("t=")
        assert json.loads(request.content)["event"] == "ping"
        blocked = check(
            await client.post(
                "/v1/webhooks/test", json={"url": "https://169.254.169.254/x"}, headers=account.headers
            )
        )
        assert blocked.status_code == 422 and blocked.json()["code"] == "url_not_allowed"
        plain = check(
            await client.post(
                "/v1/webhooks/test", json={"url": "http://example.com/x"}, headers=account.headers
            )
        )
        assert plain.status_code == 422
        assert check(await client.post("/v1/webhooks/test", json={"url": HOOK})).status_code == 401
    finally:
        await app.state.webhook_http.aclose()
        app.state.webhook_http = original
