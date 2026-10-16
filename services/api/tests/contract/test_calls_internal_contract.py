"""POST /v1/internal/calls/claim against contracts/calls.yaml, driven by the worker's own client
(003 T022). Proves the API and ``services/voice-worker/worker/internal_api.py`` agree."""

from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI

from app.calls import ports
from app.calls.ports import InboundRoute
from tests.conftest import Account
from tests.contract.conftest import check
from tests.contract.worker_compat import worker_client, worker_modules
from tests.runtime_support import SERVICE_HEADERS, Runtime, dispatch_metadata, owner_sql, start_web_call


async def _web_call(client: httpx.AsyncClient, account: Account, runtime: Runtime) -> tuple[str, str]:
    agent = runtime.versions.add_agent(account.workspace_id)
    response = check(
        await start_web_call(
            client, account.headers, agent.agent_id, dynamic_variables={"customer_name": "Priya"}
        )
    )
    assert response.status_code == 201, response.text
    body = response.json()
    return body["call_id"], body["room_name"]


async def test_worker_claims_a_web_call(
    app: FastAPI, client: httpx.AsyncClient, account: Account, runtime: Runtime
) -> None:
    internal_api, _ = worker_modules()
    api, recorder, http = worker_client(app)
    call_id, room = await _web_call(client, account, runtime)
    request = internal_api.ClaimRequest(
        job_id="AJ_first",
        room_name=room,
        worker_id="AW_1",
        dispatch_metadata=dispatch_metadata(runtime, call_id),
    )
    result = await api.claim(request)
    assert result.admitted and result.call_id == call_id
    rt = result.runtime
    assert rt.channel == "web" and rt.direction == "inbound"
    assert rt.variables["customer_name"] == "Priya" and rt.variables["call_id"] == call_id
    assert rt.limits.end_on_silence_s == 30 and rt.limits.max_duration_s == 600
    assert rt.heartbeat_interval_s == 10 and rt.caller_join_timeout_s == 60
    assert rt.recording_enabled is True and rt.stt_resolved_model == "nova-3"
    assert rt.config["llm"]["model"] == "gpt-5.1"
    # Recording starts from a job once the call is claimed (R13).
    assert "start_recording" in runtime.queue.names()

    # Idempotent per job id: the same body again.
    again = await api.claim(request)
    assert again.model_dump() == result.model_dump()
    # Another job is refused with 409.
    with pytest.raises(internal_api.ClaimRejected) as err:
        await api.claim(request.model_copy(update={"job_id": "AJ_other"}))
    assert err.value.status_code == 409
    assert owner_sql("select worker_job_id, claimed_at is not null from calls where id = %s", (call_id,)) == [
        ("AJ_first", True)
    ]
    assert all(r.status_code in (200, 409) for _, r in recorder.exchanges)
    await http.aclose()


async def test_unknown_call_is_404_and_bad_token_is_401(app: FastAPI, runtime: Runtime) -> None:
    internal_api, _ = worker_modules()
    api, _, http = worker_client(app)
    request = internal_api.ClaimRequest(
        job_id="AJ_x",
        room_name="call-x",
        worker_id="AW_1",
        dispatch_metadata={"call_id": "call_01ARZ3NDEKTSV4RRFFQ69G5FAV"},
    )
    with pytest.raises(internal_api.ClaimRejected) as err:
        await api.claim(request)
    assert err.value.status_code == 404
    await http.aclose()
    bad, _, http = worker_client(app, token="wrong-token")
    with pytest.raises(internal_api.InternalApiError) as unauthorized:
        await bad.claim(request)
    assert unauthorized.value.status_code == 401
    await http.aclose()


async def test_terminal_call_cannot_be_claimed(
    app: FastAPI, client: httpx.AsyncClient, account: Account, runtime: Runtime
) -> None:
    call_id, room = await _web_call(client, account, runtime)
    owner_sql("update calls set status = 'failed', disconnect_reason = 'error' where id = %s", (call_id,))
    response = check(
        await client.post(
            "/v1/internal/calls/claim",
            json={
                "job_id": "AJ_9",
                "room_name": room,
                "worker_id": "AW",
                "dispatch_metadata": {"call_id": call_id},
            },
            headers=SERVICE_HEADERS,
        )
    )
    assert response.status_code == 409


class Router:
    def __init__(self, route: InboundRoute | None) -> None:
        self.route = route

    async def resolve(
        self, channel: str, sip: dict[str, object], route_ref: str | None
    ) -> InboundRoute | None:
        return self.route


async def test_sip_inbound_without_router_is_refused(app: FastAPI, runtime: Runtime) -> None:
    internal_api, _ = worker_modules()
    api, _, http = worker_client(app)
    result = await api.claim(
        internal_api.ClaimRequest(
            job_id="AJ_sip0",
            room_name="sip-room-0",
            worker_id="AW",
            dispatch_metadata={"channel": "sip_inbound", "route_ref": "r1"},
            sip=internal_api.SipAttributes(caller_number="+15550001", trunk_phone_number="+15559999"),
        )
    )
    assert not result.admitted and result.refusal.disconnect_reason == "error"
    assert result.refusal.diagnostic == "no_inbound_router"
    await http.aclose()


async def test_sip_inbound_is_admitted_through_the_router(app: FastAPI, runtime: Runtime) -> None:
    internal_api, _ = worker_modules()
    _, ws = await runtime.workspace()
    agent = runtime.versions.add_agent(ws)
    ports.register_inbound_router("sip_inbound", Router(InboundRoute(ws, agent.agent_id)))
    try:
        api, _, http = worker_client(app)
        request = internal_api.ClaimRequest(
            job_id="AJ_sip1",
            room_name="sip-room-1",
            worker_id="AW",
            dispatch_metadata={"channel": "sip_inbound", "route_ref": "r1"},
            sip=internal_api.SipAttributes(
                call_id="sip-1", caller_number="+15550001", trunk_phone_number="+15559999"
            ),
        )
        result = await api.claim(request)
        assert result.admitted and result.runtime.channel == "sip_inbound"
        assert result.runtime.variables["user_number"] == "+15550001"
        again = await api.claim(request)
        assert again.call_id == result.call_id  # one call per job
        await http.aclose()
    finally:
        ports.registry.inbound_routers.clear()


async def test_sip_outbound_without_dial_provider_is_refused(app: FastAPI, runtime: Runtime) -> None:
    from app.calls import service as calls

    internal_api, _ = worker_modules()
    _, ws = await runtime.workspace()
    agent = runtime.versions.add_agent(ws)
    admission = await calls.admit(
        runtime.db,
        calls.AdmissionRequest(ws, agent.agent_id, "sip_outbound", "outbound", to_number="+15550002"),
        catalog=runtime.catalog,
    )
    api, _, http = worker_client(app)
    result = await api.claim(
        internal_api.ClaimRequest(
            job_id="AJ_out",
            room_name="out-1",
            worker_id="AW",
            dispatch_metadata={"call_id": admission.call.id},
        )
    )
    assert not result.admitted and result.refusal.diagnostic == "outbound_unavailable"
    await http.aclose()
