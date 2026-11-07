"""Inbound routing for phone numbers and the ``call_inbound`` webhook (010 T019, T063, R4, R13).

At claim time the workspace is unknown, so ``PhoneNumberRouter`` reads the number through the
security-definer ``route_phone_number`` (routing columns only), checks that the SIP trunk number
matches the number the dispatch rule names, and answers with the number's inbound agent. A
number that is not ``active`` or has no inbound agent is declined with no call row (the
dispatch rule is normally absent then, so this is the second line of defence).

When the number (or WhatsApp channel) has an inbound webhook, ``call_inbound_webhook`` POSTs a
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
from typing import Any

import httpx
from callwright_contract.url_guard import UrlNotAllowed, check_url
from callwright_contract.variables import MAX_VALUE_CHARS, MAX_VARIABLES, NAME
from opentelemetry import trace
from sqlalchemy import text

from app.calls.ports import InboundRoute
from app.core.config import Settings
from app.core.db import Database
from app.core.ids import is_valid_id, new_id
from app.core.secrets import LocalKeyWrapper
from app.core.url_guard import guarded_request
from app.phone_numbers import validation
from app.phone_numbers.shared import _resolver, agent_state
from app.webhooks_out import service as webhooks
from app.webhooks_out import signing

logger = logging.getLogger(__name__)
tracer = trace.get_tracer("app.phone_numbers")

MAX_REPLY_BYTES = 16 * 1024


@dataclass
class WebhookOutcome:
    agent_id: str
    variables: dict[str, str] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    declined: bool = False
    failure: str | None = None  # reason for ``inbound_webhook_failed:<reason>``
    ignored_agent: bool = False


def _digits(value: str | None) -> str:
    return "".join(ch for ch in value or "" if ch.isdigit())


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
            from app.agents import checks

            checked = await check_url(
                url,
                allow_http=settings.webhooks_allow_http,
                allow_private=settings.webhooks_allow_private,
                resolver=_resolver(checks.webhook_resolver),
            )
        except UrlNotAllowed:
            outcome.failure = "blocked_url"
            return outcome
        wrapper = LocalKeyWrapper(settings.secrets_master_key.get_secret_value())
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
class PhoneNumberRouter:
    db: Database
    settings: Settings
    http: httpx.AsyncClient

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
            if _digits(sip.get("trunk_phone_number")) != _digits(row.e164):
                logger.warning("inbound call for %s arrived on another trunk number; refused", route_ref)
                return None
            from_number = caller_number(sip.get("caller_number"))
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
                    channel="sip_inbound",
                    from_number=from_number,
                    to_number=row.e164,
                    agent_id=row.inbound_agent_id,
                    phone_number_id=route_ref,
                )
            return InboundRoute(
                workspace_id=row.workspace_id,
                agent_id=outcome.agent_id if outcome else row.inbound_agent_id,
                from_number=from_number,
                to_number=row.e164,
                variables=outcome.variables if outcome else {},
                phone_number_id=route_ref,
                metadata=outcome.metadata if outcome else {},
                route_detail=route_detail(outcome),
                declined=bool(outcome and outcome.declined),
                call_id=call_id,
            )
