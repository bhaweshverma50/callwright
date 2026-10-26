"""Inbound routing for WhatsApp calls (010 T054, T059, FR-027).

WhatsApp caller ids arrive without ``+``; they are normalised to E.164 before the route
lookup. Precedence: the caller's route agent when it is published, else the channel's default
agent (``route_detail`` notes ``route_skipped:unpublished_agent`` when a route was passed
over), else the call is declined with no call row and no charge. The inbound webhook runs the
same way as for phone numbers.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import httpx
from opentelemetry import trace
from sqlalchemy import text

from app.calls.ports import InboundRoute
from app.core.config import Settings
from app.core.db import Database
from app.core.ids import is_valid_id, new_id
from app.phone_numbers.routing import call_inbound_webhook, caller_number, route_detail
from app.phone_numbers.shared import agent_state
from app.whatsapp.service import ROUTABLE

tracer = trace.get_tracer("app.whatsapp")


def _digits(value: str | None) -> str:
    return "".join(ch for ch in value or "" if ch.isdigit())


@dataclass
class WhatsAppRouter:
    db: Database
    settings: Settings
    http: httpx.AsyncClient

    async def resolve(
        self, channel: str, sip: Mapping[str, Any], route_ref: str | None
    ) -> InboundRoute | None:
        with tracer.start_as_current_span("whatsapp.route") as span:
            if not route_ref or not is_valid_id(route_ref, "wa"):
                return None
            span.set_attribute("whatsapp_channel_id", route_ref)
            caller = caller_number(sip.get("caller_number"))
            async with self.db.transaction() as session:
                row = (
                    await session.execute(
                        text(
                            "select workspace_id, e164, status, default_agent_id, route_agent_id, "
                            "inbound_webhook_url from route_whatsapp_channel(:id, :caller)"
                        ),
                        {"id": route_ref, "caller": caller or ""},
                    )
                ).first()
            if row is None or row.status not in ROUTABLE:
                return None
            if _digits(sip.get("trunk_phone_number")) != _digits(row.e164):
                return None
            agent_id = None
            base_detail = None
            if row.route_agent_id:
                async with self.db.transaction(workspace_id=row.workspace_id) as session:
                    published = await agent_state(session, row.route_agent_id) == "published"
                if published:
                    agent_id = row.route_agent_id
                else:
                    base_detail = "route_skipped:unpublished_agent"
            agent_id = agent_id or row.default_agent_id
            if agent_id is None:
                span.set_attribute("route.declined", True)
                return None
            call_id = new_id("call")
            outcome = None
            if row.inbound_webhook_url:
                outcome = await call_inbound_webhook(
                    self.db,
                    self.settings,
                    self.http,
                    workspace_id=row.workspace_id,
                    url=row.inbound_webhook_url,
                    call_id=call_id,
                    channel="whatsapp",
                    from_number=caller,
                    to_number=row.e164,
                    agent_id=agent_id,
                    whatsapp_channel_id=route_ref,
                )
            return InboundRoute(
                workspace_id=row.workspace_id,
                agent_id=outcome.agent_id if outcome else agent_id,
                from_number=caller,
                to_number=row.e164,
                variables=outcome.variables if outcome else {},
                whatsapp_channel_id=route_ref,
                metadata=outcome.metadata if outcome else {},
                route_detail=route_detail(outcome, base_detail),
                declined=bool(outcome and outcome.declined),
                call_id=call_id,
            )
