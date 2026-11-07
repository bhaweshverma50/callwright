"""Inbound routing for phone numbers and WhatsApp channels, and the ``call_inbound`` webhook
(010 T019, T054, T059, T063, R4, R13, FR-027).

At claim time the workspace is unknown, so each router reads its channel through a
security-definer function (routing columns only), checks that the SIP trunk number matches the
channel's number and answers with the agent:

* ``PhoneNumberRouter``: the number's inbound agent. A number that is not ``active`` or has no
  inbound agent is declined with no call row (the dispatch rule is normally absent then, so this
  is the second line of defence).
* ``WhatsAppRouter``: WhatsApp caller ids arrive without ``+`` and are normalised to E.164
  before the lookup. The caller's route agent when it is published, else the channel's default
  agent (``route_detail`` notes ``route_skipped:unpublished_agent`` when a route was passed
  over), else the call is declined with no call row and no charge.

When the channel has an inbound webhook, ``call_inbound_webhook`` POSTs a
signed ``call_inbound`` event (003 signing scheme, URL guard, 3 s timeout, no retry). A valid
reply may switch to another published agent of the workspace, add dynamic variables and
metadata, or ``decline`` (a failed call that is never billed). Any failure is ignored and noted
in ``calls.route_detail`` as ``inbound_webhook_failed:<reason>``.
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, ClassVar

import httpx
from callwright_contract.url_guard import UrlNotAllowed
from callwright_contract.variables import MAX_VALUE_CHARS, MAX_VARIABLES, NAME
from opentelemetry import trace
from sqlalchemy import text

from app.calls.ports import InboundRoute
from app.channels import validation
from app.channels.shared import agent_state, checked_webhook_url
from app.channels.whatsapp.service import ROUTABLE
from app.core.config import Settings
from app.core.db import Database
from app.core.ids import is_valid_id, new_id
from app.core.secrets import key_wrapper
from app.core.url_guard import guarded_request
from app.webhooks_out import service as webhooks
from app.webhooks_out import signing

logger = logging.getLogger(__name__)
tracer = trace.get_tracer("app.channels")

MAX_REPLY_BYTES = 16 * 1024


@dataclass
class WebhookOutcome:
    agent_id: str
    variables: dict[str, str] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    declined: bool = False
    failure: str | None = None  # reason for ``inbound_webhook_failed:<reason>``
    ignored_agent: bool = False


def caller_number(raw: str | None) -> str | None:
    if not raw:
        return None
    try:
        return validation.normalize_whatsapp_caller(raw)
    except validation.InvalidValue:
        return raw[:64]


def parse_reply(body: bytes) -> dict[str, Any]:
    """The reply object or ``ValueError`` with the failure reason (T061)."""
    if len(body) > MAX_REPLY_BYTES:
        raise ValueError("too_large")
    if not body.strip():
        return {}
    try:
        data = json.loads(body)
    except (ValueError, UnicodeDecodeError):
        raise ValueError("invalid_json") from None
    if not isinstance(data, dict):
        raise ValueError("invalid_json")
    action = data.get("action", "answer")
    if action not in ("answer", "decline"):
        raise ValueError("invalid_reply")
    variables = data.get("dynamic_variables", {})
    if not isinstance(variables, dict) or len(variables) > MAX_VARIABLES:
        raise ValueError("invalid_reply")
    clean: dict[str, str] = {}
    for name, value in variables.items():
        if not isinstance(name, str) or not NAME.match(name) or not isinstance(value, str | int | float):
            raise ValueError("invalid_reply")
        clean[name] = str(value)[:MAX_VALUE_CHARS]
    metadata = data.get("metadata", {})
    if not isinstance(metadata, dict) or len(json.dumps(metadata, default=str).encode()) > 4096:
        raise ValueError("invalid_reply")
    agent_id = data.get("agent_id")
    if agent_id is not None and not isinstance(agent_id, str):
        raise ValueError("invalid_reply")
    return {"action": action, "dynamic_variables": clean, "metadata": metadata, "agent_id": agent_id}


async def call_inbound_webhook(
    db: Database,
    settings: Settings,
    http: httpx.AsyncClient,
    *,
    workspace_id: str,
    url: str,
    call_id: str,
    channel: str,
    from_number: str | None,
    to_number: str,
    agent_id: str,
    phone_number_id: str | None = None,
    whatsapp_channel_id: str | None = None,
) -> WebhookOutcome:
    outcome = WebhookOutcome(agent_id=agent_id)
    payload = {
        "event": "call_inbound",
        "event_id": f"evt_{uuid.uuid4().hex}",
        "call_id": call_id,
        "channel": channel,
        "from_number": from_number,
        "to_number": to_number,
        "phone_number_id": phone_number_id,
        "whatsapp_channel_id": whatsapp_channel_id,
        "agent_id": agent_id,
    }
    body = json.dumps(payload, separators=(",", ":")).encode()
    with tracer.start_as_current_span("channels.inbound_webhook") as span:
        span.set_attribute("call_id", call_id)
        if phone_number_id:
            span.set_attribute("phone_number_id", phone_number_id)
        if whatsapp_channel_id:
            span.set_attribute("whatsapp_channel_id", whatsapp_channel_id)
        try:
            checked = await checked_webhook_url(settings, url)
        except UrlNotAllowed:
            outcome.failure = "blocked_url"
            return outcome
        wrapper = key_wrapper(settings)
        async with db.transaction(workspace_id=workspace_id) as session:
            secrets = await webhooks.signing_secrets(session, wrapper, workspace_id)
        headers = {
            "Content-Type": "application/json",
            signing.HEADER: signing.sign(body, secrets),
            "Callwright-Event": "call_inbound",
        }
        try:
            response = await guarded_request(
                http,
                "POST",
                checked,
                content=body,
                headers=headers,
                timeout=settings.inbound_webhook_timeout_s,
            )
        except httpx.TimeoutException:
            outcome.failure = "timeout"
            return outcome
        except httpx.HTTPError:
            outcome.failure = "unreachable"
            return outcome
        if not 200 <= response.status_code < 300:
            outcome.failure = f"http_{response.status_code}"
            return outcome
        try:
            reply = parse_reply(response.content)
        except ValueError as exc:
            outcome.failure = str(exc)
            return outcome
        span.set_attribute("inbound_webhook.action", reply.get("action", "answer"))
    if not reply:
        return outcome
    outcome.declined = reply["action"] == "decline"
    outcome.variables = reply["dynamic_variables"]
    outcome.metadata = reply["metadata"]
    other = reply.get("agent_id")
    if other and other != agent_id:
        published = False
        if is_valid_id(other, "agt"):
            async with db.transaction(workspace_id=workspace_id) as session:
                published = await agent_state(session, other) == "published"
        if published:
            outcome.agent_id = other
        else:
            outcome.ignored_agent = True
    return outcome


def route_detail(outcome: WebhookOutcome | None, base: str | None = None) -> str | None:
    parts = [p for p in (base,) if p]
    if outcome is not None:
        if outcome.failure:
            parts.append(f"inbound_webhook_failed:{outcome.failure}")
        elif outcome.declined:
            parts.append("declined_by_webhook")
        elif outcome.ignored_agent:
            parts.append("inbound_webhook_agent_ignored")
    return ";".join(parts)[:200] or None


@dataclass
class _InboundRouter:
    """003's ``InboundRouter`` for one channel kind: the trunk-number check and the route (call id,
    inbound webhook, routing outcome) are the same for numbers and WhatsApp channels."""

    db: Database
    settings: Settings
    http: httpx.AsyncClient
    channel: ClassVar[str]
    id_field: ClassVar[str]

    def _same_trunk(self, sip: Mapping[str, Any], e164: str, route_ref: str) -> bool:
        if validation.digits(sip.get("trunk_phone_number")) == validation.digits(e164):
            return True
        logger.warning("inbound call for %s arrived on another trunk number; refused", route_ref)
        return False

    async def _route(
        self,
        *,
        workspace_id: str,
        route_ref: str,
        e164: str,
        agent_id: str,
        from_number: str | None,
        webhook_url: str | None,
        base_detail: str | None = None,
    ) -> InboundRoute:
        call_id = new_id("call")
        ids = {self.id_field: route_ref}
        outcome = None
        if webhook_url:
            outcome = await call_inbound_webhook(
                self.db,
                self.settings,
                self.http,
                workspace_id=workspace_id,
                url=webhook_url,
                call_id=call_id,
                channel=self.channel,
                from_number=from_number,
                to_number=e164,
                agent_id=agent_id,
                **ids,
            )
        return InboundRoute(
            workspace_id=workspace_id,
            agent_id=outcome.agent_id if outcome else agent_id,
            from_number=from_number,
            to_number=e164,
            variables=outcome.variables if outcome else {},
            metadata=outcome.metadata if outcome else {},
            route_detail=route_detail(outcome, base_detail),
            declined=bool(outcome and outcome.declined),
            call_id=call_id,
            **ids,
        )


@dataclass
class PhoneNumberRouter(_InboundRouter):
    channel: ClassVar[str] = "sip_inbound"
    id_field: ClassVar[str] = "phone_number_id"

    async def resolve(
        self, channel: str, sip: Mapping[str, Any], route_ref: str | None
    ) -> InboundRoute | None:
        with tracer.start_as_current_span("phone_numbers.route") as span:
            if not route_ref or not is_valid_id(route_ref, "num"):
                return None
            span.set_attribute("phone_number_id", route_ref)
            async with self.db.transaction() as session:
                row = (
                    await session.execute(
                        text(
                            "select workspace_id, e164, status, inbound_agent_id, inbound_webhook_url "
                            "from route_phone_number(:id)"
                        ),
                        {"id": route_ref},
                    )
                ).first()
            if row is None or row.status != "active" or row.inbound_agent_id is None:
                span.set_attribute("route.declined", True)
                return None
            if not self._same_trunk(sip, row.e164, route_ref):
                return None
            return await self._route(
                workspace_id=row.workspace_id,
                route_ref=route_ref,
                e164=row.e164,
                agent_id=row.inbound_agent_id,
                from_number=caller_number(sip.get("caller_number")),
                webhook_url=row.inbound_webhook_url,
            )


@dataclass
class WhatsAppRouter(_InboundRouter):
    channel: ClassVar[str] = "whatsapp"
    id_field: ClassVar[str] = "whatsapp_channel_id"

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
            if not self._same_trunk(sip, row.e164, route_ref):
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
            return await self._route(
                workspace_id=row.workspace_id,
                route_ref=route_ref,
                e164=row.e164,
                agent_id=agent_id,
                from_number=caller,
                webhook_url=row.inbound_webhook_url,
                base_detail=base_detail,
            )
