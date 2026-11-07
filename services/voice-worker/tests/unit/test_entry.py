"""Job entry helpers: dispatch metadata, claim from a SIP room, telephony helpers, roles."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any, ClassVar

import httpx
import pytest
import respx

from tests.harness.runner import CALL_ID
from worker.entry import claim_job, create_server, parse_dispatch_metadata
from worker.internal_api import InternalApiClient
from worker.settings import WorkerSettings
from worker.telephony import dtmf_code, sip_attributes

BASE = "http://api.test/v1/internal"


def test_parse_dispatch_metadata() -> None:
    assert parse_dispatch_metadata(json.dumps({"call_id": CALL_ID})) == {"call_id": CALL_ID}
    assert parse_dispatch_metadata("") == {}
    assert parse_dispatch_metadata("not json") == {"raw": "not json"}
    assert parse_dispatch_metadata("[1]") == {"raw": "[1]"}


def test_sip_attributes_and_dtmf_codes() -> None:
    sip = sip_attributes(
        {"sip.callID": "SCL_1", "sip.trunkPhoneNumber": "+15550100", "sip.phoneNumber": "+1555"},
        "sip_caller",
    )
    assert sip.call_id == "SCL_1" and sip.caller_number == "+1555"
    assert sip.participant_identity == "sip_caller" and sip.trunk_id is None
    assert [dtmf_code(d) for d in "09*#"] == [0, 9, 10, 11]
    with pytest.raises(ValueError):
        dtmf_code("A")


class AgentServer:
    """Stands in for ``livekit.agents.AgentServer``: keeps the options it was created with."""

    def __init__(self, **options: Any) -> None:
        self.options = options

    def rtc_session(self, entrypoint: Any, *, agent_name: str) -> None:
        self.agent_name = agent_name


@pytest.fixture
def server_options(monkeypatch: pytest.MonkeyPatch) -> None:
    import livekit.agents

    monkeypatch.setattr(livekit.agents, "AgentServer", AgentServer)


@pytest.mark.usefixtures("server_options")
def test_create_server_applies_capacity_settings() -> None:
    settings = WorkerSettings.model_validate(
        {"WORKER_NUM_IDLE_PROCESSES": "2", "WORKER_LOAD_THRESHOLD": "0.9"}
    )
    server = create_server(settings)
    assert server.options["num_idle_processes"] == 2
    assert server.options["load_threshold"] == 0.9
    assert server.agent_name == settings.agent_name


@pytest.mark.usefixtures("server_options")
def test_create_server_keeps_framework_defaults_when_unset() -> None:
    options = create_server(WorkerSettings()).options
    assert "num_idle_processes" not in options and "load_threshold" not in options


class Participant:
    identity = "sip_caller"
    attributes: ClassVar[dict[str, str]] = {
        "sip.callID": "SCL_9",
        "sip.trunkPhoneNumber": "+15550100",
    }


def fake_ctx(metadata: dict[str, Any]) -> Any:
    async def wait_for_participant() -> Participant:
        return Participant()

    return SimpleNamespace(
        job=SimpleNamespace(id="AJ_1", metadata=json.dumps(metadata)),
        room=SimpleNamespace(name="call-room"),
        worker_id="AW_1",
        wait_for_participant=wait_for_participant,
    )


@respx.mock
async def test_claim_job_for_inbound_sip_sends_attributes() -> None:
    route = respx.post(f"{BASE}/calls/claim").mock(
        return_value=httpx.Response(
            200,
            json={
                "admitted": False,
                "call_id": CALL_ID,
                "refusal": {"disconnect_reason": "insufficient_credit"},
            },
        )
    )
    call_id, runtime, refusal = await claim_job(
        fake_ctx({"channel": "sip_inbound", "route_ref": "num_1"}), InternalApiClient(BASE, "t")
    )
    body = json.loads(route.calls.last.request.content)
    assert body["sip"] == {
        "call_id": "SCL_9",
        "trunk_phone_number": "+15550100",
        "participant_identity": "sip_caller",
    }
    assert body["dispatch_metadata"] == {"channel": "sip_inbound", "route_ref": "num_1"}
    assert call_id == CALL_ID and runtime is None
    assert refusal.disconnect_reason == "insufficient_credit"


@respx.mock
async def test_claim_job_for_web_call_has_no_sip_block() -> None:
    route = respx.post(f"{BASE}/calls/claim").mock(
        return_value=httpx.Response(200, json={"admitted": False, "call_id": CALL_ID})
    )
    await claim_job(fake_ctx({"call_id": CALL_ID}), InternalApiClient(BASE, "t"))
    assert "sip" not in json.loads(route.calls.last.request.content)
