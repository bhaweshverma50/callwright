"""LiveKit SIP objects for one phone number (010 T016, T039, research R1, R2).

``provision`` creates whatever the number is missing (inbound trunk, outbound trunk and, with an
inbound agent, the dispatch rule), reusing stored ids, so a retry after a failure is
idempotent. A failure deletes the objects created by that attempt (compensation) and reports
the reason; nothing half-made is left behind. ``update_trunks`` applies edits with the update
API and falls back to create-new-then-delete-old, which is safe because established calls do not
reference a trunk after setup.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from callwright_contract.protocol import DISPATCH_CHANNEL, DISPATCH_ROUTE_REF
from opentelemetry import trace

from app.core.sip import DispatchRuleSpec, InboundTrunkSpec, OutboundTrunkSpec, SipError, SipGateway
from app.phone_numbers.models import PhoneNumber

logger = logging.getLogger(__name__)
tracer = trace.get_tracer("app.phone_numbers")


@dataclass
class SipObjects:
    inbound_trunk_id: str | None
    outbound_trunk_id: str | None
    dispatch_rule_id: str | None


@dataclass
class ProvisionResult:
    objects: SipObjects
    error: str | None = None


def inbound_spec(number: PhoneNumber) -> InboundTrunkSpec:
    return InboundTrunkSpec(
        name=f"callwright {number.id}",
        numbers=[number.e164],
        allowed_addresses=[str(c) for c in number.inbound_allowed_cidrs or []],
        metadata=json.dumps({"phone_number_id": number.id}),
    )


def outbound_spec(number: PhoneNumber, password: str | None) -> OutboundTrunkSpec:
    return OutboundTrunkSpec(
        name=f"callwright {number.id}",
        address=number.termination_address,
        transport=number.transport,
        numbers=[number.e164],
        auth_username=number.auth_username,
        auth_password=password if number.auth_username or password else None,
        metadata=json.dumps({"phone_number_id": number.id}),
    )


def dispatch_spec(trunk_id: str, channel: str, route_ref: str, agent_name: str) -> DispatchRuleSpec:
    return DispatchRuleSpec(
        name=f"callwright {route_ref}",
        trunk_ids=[trunk_id],
        agent_name=agent_name,
        agent_metadata={DISPATCH_CHANNEL: channel, DISPATCH_ROUTE_REF: route_ref},
    )


async def _compensate(sip: SipGateway, created: list[tuple[str, str]]) -> None:
    for kind, object_id in reversed(created):
        try:
            if kind == "rule":
                await sip.delete_dispatch_rule(object_id)
            else:
                await sip.delete_trunk(object_id)
        except SipError:
            logger.warning("compensation could not delete %s %s", kind, object_id)


async def provision(
    sip: SipGateway, number: PhoneNumber, password: str | None, *, agent_name: str
) -> ProvisionResult:
    """Create the missing SIP objects for ``number`` (stored ids are reused)."""
    objects = SipObjects(number.lk_inbound_trunk_id, number.lk_outbound_trunk_id, number.lk_dispatch_rule_id)
    created: list[tuple[str, str]] = []
    with tracer.start_as_current_span("phone_numbers.provision") as span:
        span.set_attribute("phone_number_id", number.id)
        try:
            if objects.inbound_trunk_id is None:
                objects.inbound_trunk_id = await sip.create_inbound_trunk(inbound_spec(number))
                created.append(("trunk", objects.inbound_trunk_id))
            if objects.outbound_trunk_id is None:
                objects.outbound_trunk_id = await sip.create_outbound_trunk(outbound_spec(number, password))
                created.append(("trunk", objects.outbound_trunk_id))
            if number.inbound_agent_id and objects.dispatch_rule_id is None:
                objects.dispatch_rule_id = await sip.create_dispatch_rule(
                    dispatch_spec(objects.inbound_trunk_id, "sip_inbound", number.id, agent_name)
                )
                created.append(("rule", objects.dispatch_rule_id))
        except SipError as exc:
            span.set_attribute("error", True)
            await _compensate(sip, created)
            created_ids = {object_id for _, object_id in created}
            return ProvisionResult(
                SipObjects(
                    None if objects.inbound_trunk_id in created_ids else objects.inbound_trunk_id,
                    None if objects.outbound_trunk_id in created_ids else objects.outbound_trunk_id,
                    None if objects.dispatch_rule_id in created_ids else objects.dispatch_rule_id,
                ),
                error=str(exc),
            )
    return ProvisionResult(objects)


async def attach_rule(sip: SipGateway, number: PhoneNumber, *, agent_name: str) -> str:
    assert number.lk_inbound_trunk_id is not None
    return await sip.create_dispatch_rule(
        dispatch_spec(number.lk_inbound_trunk_id, "sip_inbound", number.id, agent_name)
    )


async def _replace_trunk[S: (InboundTrunkSpec, OutboundTrunkSpec)](
    sip: SipGateway,
    old_id: str,
    create: Callable[[S], Awaitable[str]],
    update: Callable[[str, S], Awaitable[None]],
    spec: S,
) -> str:
    """Update in place; when the update fails, create a new trunk and delete the old one."""
    try:
        await update(old_id, spec)
        return old_id
    except SipError:
        new_id = await create(spec)
        try:
            await sip.delete_trunk(old_id)
        except SipError:
            logger.warning("could not delete replaced trunk %s", old_id)
        return new_id


async def update_trunks(
    sip: SipGateway,
    number: PhoneNumber,
    password: str | None,
    *,
    inbound_changed: bool,
    outbound_changed: bool,
) -> tuple[str | None, str | None]:
    """Apply edits to the number's trunks; returns the (possibly new) trunk ids.

    Raises ``SipError`` when neither the update nor the replacement worked; nothing changed."""
    inbound_id, outbound_id = number.lk_inbound_trunk_id, number.lk_outbound_trunk_id
    with tracer.start_as_current_span("phone_numbers.update_trunks") as span:
        span.set_attribute("phone_number_id", number.id)
        if inbound_changed and inbound_id:
            inbound_id = await _replace_trunk(
                sip, inbound_id, sip.create_inbound_trunk, sip.update_inbound_trunk, inbound_spec(number)
            )
        if outbound_changed and outbound_id:
            outbound_id = await _replace_trunk(
                sip,
                outbound_id,
                sip.create_outbound_trunk,
                sip.update_outbound_trunk,
                outbound_spec(number, password),
            )
    return inbound_id, outbound_id


async def remove_all(sip: SipGateway, number: PhoneNumber) -> None:
    """Delete the dispatch rule and both trunks (raises ``SipError`` on the first failure)."""
    if number.lk_dispatch_rule_id:
        await sip.delete_dispatch_rule(number.lk_dispatch_rule_id)
    for trunk_id in (number.lk_inbound_trunk_id, number.lk_outbound_trunk_id):
        if trunk_id:
            await sip.delete_trunk(trunk_id)
