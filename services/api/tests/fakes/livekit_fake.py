"""Channel test support (010 T010): a fresh in-memory SIP service and WhatsApp Graph per test,
010's routers re-installed, and small helpers for numbers, outbound calls and SIP claims.

Import the ``channels`` fixture into a test module with
``from tests.fakes.livekit_fake import channels  # noqa: F401``.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import httpx
import pytest_asyncio
from fastapi import FastAPI

from app.phone_numbers.install import install
from app.phone_numbers.sip import FakeSip
from app.whatsapp.graph_client import FakeWhatsAppGraph
from tests.conftest import Account
from tests.runtime_support import SERVICE_HEADERS, Runtime


def fresh_e164() -> str:
    """A unique, valid-looking US number in the 415 area code."""
    n = uuid.uuid4().int
    return f"+1415{2 + n % 8}{(n // 8) % 1_000_000:06d}"


def whatsapp_body(**overrides: Any) -> dict[str, Any]:
    n = uuid.uuid4().int
    return {
        "meta_phone_number_id": str(100_000_000_000 + n % 10**11),
        "e164": fresh_e164(),
        "label": "Support WhatsApp",
        "access_token": f"EAAG-token-{n % 10**8:08d}",
        "verify_token": f"verify-{n % 10**10:010d}",
        "app_secret": f"appsecret-{n % 10**8:08d}",
        **overrides,
    }


@dataclass
class Channels:
    app: FastAPI
    sip: FakeSip
    graph: FakeWhatsAppGraph
    runtime: Runtime

    async def number(self, client: httpx.AsyncClient, account: Account, **body: Any) -> dict[str, Any]:
        payload = {
            "e164": fresh_e164(),
            "label": "Main Office Line",
            "termination_address": "trunk.example-carrier.com:5060",
            **body,
        }
        response = await client.post("/v1/phone-numbers", json=payload, headers=account.headers)
        assert response.status_code == 201, response.text
        result: dict[str, Any] = response.json()
        return result

    def agent(self, workspace_id: str, *, published: bool = True, **config: Any) -> str:
        from tests.runtime_support import agent_config

        return self.runtime.versions.add_agent(
            workspace_id, agent_config(**config) if config else None, published=published
        ).agent_id

    async def all_day(self, client: httpx.AsyncClient, account: Account, value: Any = "all") -> None:
        """Calling hours for every weekday: ``"all"`` (00:00 to 24:00) or ``None`` (no calls)."""
        window = {"start": "00:00", "end": "24:00"} if value == "all" else value
        days = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
        response = await client.put(
            "/v1/outbound-calling-hours",
            json={"windows": dict.fromkeys(days, window)},
            headers=account.headers,
        )
        assert response.status_code == 200, response.text

    async def outbound_ready(self, client: httpx.AsyncClient, account: Account) -> tuple[dict[str, Any], str]:
        """An active number with a published outbound agent, calls allowed at any hour."""
        agent = self.agent(account.workspace_id)
        number = await self.number(client, account, outbound_agent_id=agent)
        await self.all_day(client, account)
        return number, agent

    async def place(
        self, client: httpx.AsyncClient, account: Account, key: str | None = None, **body: Any
    ) -> httpx.Response:
        headers = {**account.headers, "Idempotency-Key": key or f"key-{uuid.uuid4().hex}"}
        return await client.post("/v1/outbound-calls", json=body, headers=headers)

    async def whatsapp(self, client: httpx.AsyncClient, account: Account, **body: Any) -> dict[str, Any]:
        payload = whatsapp_body(**body)
        response = await client.post("/v1/whatsapp/channels", json=payload, headers=account.headers)
        assert response.status_code == 201, response.text
        result: dict[str, Any] = response.json()
        return result

    async def claim_inbound(
        self,
        client: httpx.AsyncClient,
        *,
        channel: str,
        route_ref: str,
        trunk_number: str,
        caller: str = "+14155550123",
        job_id: str | None = None,
    ) -> dict[str, Any]:
        response = await client.post(
            "/v1/internal/calls/claim",
            json={
                "job_id": job_id or f"AJ_{uuid.uuid4().hex[:10]}",
                "room_name": f"call-in-{uuid.uuid4().hex[:8]}",
                "worker_id": "AW_test",
                "dispatch_metadata": {"channel": channel, "route_ref": route_ref},
                "sip": {
                    "call_id": f"SCL_{uuid.uuid4().hex[:8]}",
                    "trunk_phone_number": trunk_number,
                    "caller_number": caller,
                    "participant_identity": "sip_caller",
                },
            },
            headers=SERVICE_HEADERS,
        )
        assert response.status_code == 200, response.text
        body: dict[str, Any] = response.json()
        return body


@pytest_asyncio.fixture
async def channels(app: FastAPI, runtime: Runtime) -> AsyncIterator[Channels]:
    previous_sip, previous_graph = app.state.sip, app.state.whatsapp_graph
    sip, graph = FakeSip(), FakeWhatsAppGraph()
    app.state.sip, app.state.whatsapp_graph = sip, graph
    install(app.state)
    await app.state.redis.delete(*[k async for k in app.state.redis.scan_iter("tb:outbound:*")] or ["-"])
    try:
        yield Channels(app, sip, graph, runtime)
    finally:
        app.state.sip, app.state.whatsapp_graph = previous_sip, previous_graph
