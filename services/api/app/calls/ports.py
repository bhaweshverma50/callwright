"""Extension points of the calls module (003 plan "Extension points", T018).

Later or parallel features register implementations here; until they do, the defaults keep the
API working with clear refusals.

* ``AgentVersionsPort`` (002): frozen agent versions. 003 codes against this protocol; the
  integrator registers 002's ``agent_versions.service`` with ``set_agent_versions`` at merge.
  ``get_snapshot(version_id)`` returns the frozen AgentConfig of one version;
  ``snapshot_for_test(agent_id)`` the version for the current draft (created with
  ``source = test`` when the draft changed, never published); ``get_published(agent_id)`` the
  pinned version or None. Every method receives the caller's RLS-scoped session.
* ``InboundRouter`` (010): resolves an inbound SIP or WhatsApp call to workspace and agent.
* ``OutboundDialProvider`` (010): trunk and numbers for ``sip_outbound`` claims.
* ``ObjectSigner``: short-lived GET URLs for objects (uploaded ambience, recordings).
* ``flow_runtime_available`` (004): flow agents are refused until 004 says it can run them.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True)
class AgentSnapshot:
    """One immutable agent version as 003 needs it."""

    version_id: str
    agent_id: str
    workspace_id: str
    agent_type: str  # single_prompt | flow
    config: Mapping[str, Any]


class AgentVersionsPort(Protocol):
    async def agent_exists(self, session: AsyncSession, agent_id: str) -> bool: ...

    async def get_snapshot(self, session: AsyncSession, version_id: str) -> AgentSnapshot | None: ...

    async def snapshot_for_test(self, session: AsyncSession, agent_id: str) -> AgentSnapshot | None: ...

    async def get_published(self, session: AsyncSession, agent_id: str) -> AgentSnapshot | None: ...


class NoAgentVersions:
    """Default until 002 is wired: no agent exists, so every call request is a 404."""

    async def agent_exists(self, session: AsyncSession, agent_id: str) -> bool:
        return False

    async def get_snapshot(self, session: AsyncSession, version_id: str) -> AgentSnapshot | None:
        return None

    async def snapshot_for_test(self, session: AsyncSession, agent_id: str) -> AgentSnapshot | None:
        return None

    async def get_published(self, session: AsyncSession, agent_id: str) -> AgentSnapshot | None:
        return None


@dataclass(frozen=True)
class InboundRoute:
    workspace_id: str
    agent_id: str
    from_number: str | None = None
    to_number: str | None = None
    variables: Mapping[str, str] = field(default_factory=dict)
    phone_number_id: str | None = None
    whatsapp_channel_id: str | None = None
    # 010: reply metadata from the inbound webhook, the routing outcome for ``calls.route_detail``
    # and a decline by that webhook (admitted as a failed, never billed call).
    metadata: Mapping[str, Any] = field(default_factory=dict)
    route_detail: str | None = None
    declined: bool = False
    call_id: str | None = None  # the id already sent to the inbound webhook, if any


class InboundRouter(Protocol):
    async def resolve(
        self, channel: str, sip: Mapping[str, Any], route_ref: str | None
    ) -> InboundRoute | None: ...


@dataclass(frozen=True)
class OutboundDial:
    sip_trunk_id: str
    to_number: str
    from_number: str
    ring_timeout_s: int = 30


class OutboundDialProvider(Protocol):
    async def dial_spec(self, session: AsyncSession, call: Any) -> OutboundDial | None: ...


class ObjectSigner(Protocol):
    def presign_get(self, bucket: str, key: str, ttl_s: int) -> str: ...


@dataclass
class Registry:
    agent_versions: AgentVersionsPort = field(default_factory=NoAgentVersions)
    inbound_routers: dict[str, InboundRouter] = field(default_factory=dict)
    outbound_dial: OutboundDialProvider | None = None
    signer: ObjectSigner | None = None
    flow_runtime_available: bool = False


registry = Registry()


def set_agent_versions(port: AgentVersionsPort) -> None:
    registry.agent_versions = port


def register_inbound_router(channel: str, router: InboundRouter) -> None:
    registry.inbound_routers[channel] = router


def set_outbound_dial_provider(provider: OutboundDialProvider | None) -> None:
    registry.outbound_dial = provider


def set_object_signer(signer: ObjectSigner | None) -> None:
    registry.signer = signer


def set_flow_runtime_available(available: bool) -> None:
    registry.flow_runtime_available = available
