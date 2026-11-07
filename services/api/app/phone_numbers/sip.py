"""LiveKit SIP objects for channels (010 T008, research R1, R2, R10).

Every imported number gets one inbound trunk, one outbound trunk and, while an inbound agent is
attached, one dispatch rule; a WhatsApp channel gets an inbound trunk (Meta's digest credentials,
TLS media) and a dispatch rule. ``SipGateway`` is the port:

* ``LiveKitSip`` (``sip_live``) calls LiveKit's SIP service through ``livekit-api``
  with a per-call timeout. Every failure is a ``SipError`` with a short operator-safe message.
* ``FakeSip`` keeps objects in memory (tests, offline development and deployments without a
  ``livekit-sip`` service). ``fail_next`` makes the next named operation fail.

Deleting an object that no longer exists is not an error, so compensation and retries are
idempotent.
"""

from __future__ import annotations

import asyncio
import itertools
import json
from collections.abc import Awaitable, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol, TypeVar

from livekit import api as lk

from app.core.config import Settings
from app.core.livekit import http_url

T = TypeVar("T")

TRANSPORTS = {
    "auto": "SIP_TRANSPORT_AUTO",
    "udp": "SIP_TRANSPORT_UDP",
    "tcp": "SIP_TRANSPORT_TCP",
    "tls": "SIP_TRANSPORT_TLS",
}
INBOUND_ROOM_PREFIX = "call-in-"


class SipError(Exception):
    """The SIP service refused or failed a request; ``str(exc)`` is safe to show."""


@dataclass(frozen=True)
class InboundTrunkSpec:
    name: str
    numbers: Sequence[str]
    allowed_addresses: Sequence[str] = ()
    auth_username: str | None = None
    auth_password: str | None = None
    require_media_encryption: bool = False
    metadata: str = ""


@dataclass(frozen=True)
class OutboundTrunkSpec:
    name: str
    address: str
    transport: str
    numbers: Sequence[str]
    auth_username: str | None = None
    auth_password: str | None = None
    metadata: str = ""


@dataclass(frozen=True)
class DispatchRuleSpec:
    """An individual-room rule that dispatches the voice worker with routing metadata."""

    name: str
    trunk_ids: Sequence[str]
    agent_name: str
    agent_metadata: dict[str, str]
    room_prefix: str = INBOUND_ROOM_PREFIX


class SipGateway(Protocol):
    live: bool

    async def create_inbound_trunk(self, spec: InboundTrunkSpec) -> str: ...

    async def update_inbound_trunk(self, trunk_id: str, spec: InboundTrunkSpec) -> None: ...

    async def create_outbound_trunk(self, spec: OutboundTrunkSpec) -> str: ...

    async def update_outbound_trunk(self, trunk_id: str, spec: OutboundTrunkSpec) -> None: ...

    async def delete_trunk(self, trunk_id: str) -> None: ...

    async def create_dispatch_rule(self, spec: DispatchRuleSpec) -> str: ...

    async def delete_dispatch_rule(self, rule_id: str) -> None: ...

    async def aclose(self) -> None: ...


def _inbound_info(spec: InboundTrunkSpec) -> lk.SIPInboundTrunkInfo:
    return lk.SIPInboundTrunkInfo(
        name=spec.name,
        numbers=list(spec.numbers),
        allowed_addresses=list(spec.allowed_addresses),
        auth_username=spec.auth_username or "",
        auth_password=spec.auth_password or "",
        media_encryption=(
            lk.SIPMediaEncryption.SIP_MEDIA_ENCRYPT_REQUIRE
            if spec.require_media_encryption
            else lk.SIPMediaEncryption.SIP_MEDIA_ENCRYPT_ALLOW
        ),
        metadata=spec.metadata,
    )


def _outbound_info(spec: OutboundTrunkSpec) -> lk.SIPOutboundTrunkInfo:
    return lk.SIPOutboundTrunkInfo(
        name=spec.name,
        address=spec.address,
        transport=TRANSPORTS[spec.transport],
        numbers=list(spec.numbers),
        auth_username=spec.auth_username or "",
        auth_password=spec.auth_password or "",
        metadata=spec.metadata,
    )


class LiveKitSip:
    live = True

    def __init__(self, settings: Settings) -> None:
        self._url = http_url(settings.livekit_url)
        self._key = settings.livekit_api_key.get_secret_value()
        self._secret = settings.livekit_api_secret.get_secret_value()
        self._timeout = settings.sip_api_timeout_s
        self._api: lk.LiveKitAPI | None = None

    def _sip(self) -> Any:
        if self._api is None:
            self._api = lk.LiveKitAPI(self._url, self._key, self._secret)
        return self._api.sip

    async def _call(self, op: str, coro: Awaitable[T], *, missing_ok: bool = False) -> T | None:
        try:
            return await asyncio.wait_for(coro, self._timeout)
        except TimeoutError as exc:
            raise SipError(f"The SIP service did not answer {op} within {self._timeout:g} s.") from exc
        except lk.TwirpError as exc:
            if missing_ok and exc.code == lk.TwirpErrorCode.NOT_FOUND:
                return None
            raise SipError(f"The SIP service refused {op}: {exc.message}"[:300]) from exc
        except Exception as exc:
            raise SipError(f"The SIP service could not be reached for {op}.") from exc

    async def create_inbound_trunk(self, spec: InboundTrunkSpec) -> str:
        info = await self._call(
            "inbound trunk creation",
            self._sip().create_inbound_trunk(lk.CreateSIPInboundTrunkRequest(trunk=_inbound_info(spec))),
        )
        assert info is not None
        return str(info.sip_trunk_id)

    async def update_inbound_trunk(self, trunk_id: str, spec: InboundTrunkSpec) -> None:
        info = _inbound_info(spec)
        info.sip_trunk_id = trunk_id
        await self._call("inbound trunk update", self._sip().update_inbound_trunk(trunk_id, info))

    async def create_outbound_trunk(self, spec: OutboundTrunkSpec) -> str:
        info = await self._call(
            "outbound trunk creation",
            self._sip().create_outbound_trunk(lk.CreateSIPOutboundTrunkRequest(trunk=_outbound_info(spec))),
        )
        assert info is not None
        return str(info.sip_trunk_id)

    async def update_outbound_trunk(self, trunk_id: str, spec: OutboundTrunkSpec) -> None:
        info = _outbound_info(spec)
        info.sip_trunk_id = trunk_id
        await self._call("outbound trunk update", self._sip().update_outbound_trunk(trunk_id, info))

    async def delete_trunk(self, trunk_id: str) -> None:
        await self._call(
            "trunk deletion",
            self._sip().delete_trunk(lk.DeleteSIPTrunkRequest(sip_trunk_id=trunk_id)),
            missing_ok=True,
        )

    async def create_dispatch_rule(self, spec: DispatchRuleSpec) -> str:
        request = lk.CreateSIPDispatchRuleRequest(
            name=spec.name,
            trunk_ids=list(spec.trunk_ids),
            rule=lk.SIPDispatchRule(
                dispatch_rule_individual=lk.SIPDispatchRuleIndividual(room_prefix=spec.room_prefix)
            ),
            room_config=lk.RoomConfiguration(
                agents=[
                    lk.RoomAgentDispatch(agent_name=spec.agent_name, metadata=json.dumps(spec.agent_metadata))
                ]
            ),
        )
        info = await self._call("dispatch rule creation", self._sip().create_dispatch_rule(request))
        assert info is not None
        return str(info.sip_dispatch_rule_id)

    async def delete_dispatch_rule(self, rule_id: str) -> None:
        await self._call(
            "dispatch rule deletion",
            self._sip().delete_dispatch_rule(lk.DeleteSIPDispatchRuleRequest(sip_dispatch_rule_id=rule_id)),
            missing_ok=True,
        )

    async def aclose(self) -> None:
        if self._api is not None:
            await self._api.aclose()
            self._api = None


@dataclass
class FakeSip:
    """In-memory SIP service. Ids look like LiveKit's (``ST_``, ``SDR_``)."""

    live: bool = False
    inbound: dict[str, InboundTrunkSpec] = field(default_factory=dict)
    outbound: dict[str, OutboundTrunkSpec] = field(default_factory=dict)
    rules: dict[str, DispatchRuleSpec] = field(default_factory=dict)
    fail_next: set[str] = field(default_factory=set)
    calls: list[str] = field(default_factory=list)
    _seq: itertools.count[int] = field(default_factory=lambda: itertools.count(1))

    def _maybe_fail(self, op: str) -> None:
        self.calls.append(op)
        if op in self.fail_next:
            self.fail_next.discard(op)
            raise SipError(f"The SIP service refused {op.replace('_', ' ')} (simulated).")

    def _id(self, prefix: str) -> str:
        return f"{prefix}_fake{next(self._seq):06d}"

    async def create_inbound_trunk(self, spec: InboundTrunkSpec) -> str:
        self._maybe_fail("create_inbound_trunk")
        trunk_id = self._id("ST")
        self.inbound[trunk_id] = spec
        return trunk_id

    async def update_inbound_trunk(self, trunk_id: str, spec: InboundTrunkSpec) -> None:
        self._maybe_fail("update_inbound_trunk")
        if trunk_id not in self.inbound:
            raise SipError("The SIP service refused inbound trunk update: not found")
        self.inbound[trunk_id] = spec

    async def create_outbound_trunk(self, spec: OutboundTrunkSpec) -> str:
        self._maybe_fail("create_outbound_trunk")
        trunk_id = self._id("ST")
        self.outbound[trunk_id] = spec
        return trunk_id

    async def update_outbound_trunk(self, trunk_id: str, spec: OutboundTrunkSpec) -> None:
        self._maybe_fail("update_outbound_trunk")
        if trunk_id not in self.outbound:
            raise SipError("The SIP service refused outbound trunk update: not found")
        self.outbound[trunk_id] = spec

    async def delete_trunk(self, trunk_id: str) -> None:
        self._maybe_fail("delete_trunk")
        self.inbound.pop(trunk_id, None)
        self.outbound.pop(trunk_id, None)

    async def create_dispatch_rule(self, spec: DispatchRuleSpec) -> str:
        self._maybe_fail("create_dispatch_rule")
        rule_id = self._id("SDR")
        self.rules[rule_id] = spec
        return rule_id

    async def delete_dispatch_rule(self, rule_id: str) -> None:
        self._maybe_fail("delete_dispatch_rule")
        self.rules.pop(rule_id, None)

    async def aclose(self) -> None:
        return None


def sip_live(settings: Settings) -> bool:
    """Trunks and dispatch rules go to LiveKit's SIP API: ``SIP_MODE=live``, or ``auto`` with
    ``LIVEKIT_MODE=live`` and ``LIVEKIT_SIP_HOST`` set."""
    if settings.sip_mode == "auto":
        return settings.livekit_mode == "live" and bool(settings.livekit_sip_host)
    return settings.sip_mode == "live"


def build_sip(settings: Settings) -> SipGateway:
    return LiveKitSip(settings) if sip_live(settings) else FakeSip()
