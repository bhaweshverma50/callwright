"""WhatsApp Cloud API calls for voice channels (010 T050, T084, research R10).

All calls use the operator's access token for one business phone number:

1. ``check_number``: ``GET /{version}/{phone_number_id}?fields=display_phone_number,verified_name``
   proves the token can read the number and gives the number to compare.
2. ``enable_calling``: ``POST /{version}/{phone_number_id}/settings`` turns on Calling with SIP
   delivery to our SIP host (TLS, port 5061).
3. ``sip_credentials``: ``GET .../settings?include_sip_credentials=true`` returns the digest
   password Meta uses when it sends the INVITE; the user name is the business number's digits.
4. ``disable_calling``: best effort when a channel is deleted.

Errors are ``GraphError`` with ``kind`` ``rejected`` (Meta answered 4xx: bad token, unknown id,
missing permission; ``message`` is Meta's text) or ``unreachable`` (connection error, timeout,
5xx). ``FakeWhatsAppGraph`` answers locally for tests and deployments without telephony.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

import httpx

from app.core.config import Settings

SIP_PORT = 5061


class GraphError(Exception):
    def __init__(self, kind: Literal["rejected", "unreachable"], message: str) -> None:
        super().__init__(message)
        self.kind = kind
        self.message = message


@dataclass(frozen=True)
class NumberInfo:
    display_phone_number: str | None
    verified_name: str | None = None


@dataclass(frozen=True)
class SipCredentials:
    username: str
    password: str


class WhatsAppGraph(Protocol):
    live: bool

    async def check_number(self, token: str, version: str, phone_number_id: str) -> NumberInfo: ...

    async def enable_calling(self, token: str, version: str, phone_number_id: str, sip_host: str) -> None: ...

    async def sip_credentials(
        self, token: str, version: str, phone_number_id: str, e164: str
    ) -> SipCredentials | None: ...

    async def disable_calling(self, token: str, version: str, phone_number_id: str) -> None: ...

    async def aclose(self) -> None: ...


def _version(version: str) -> str:
    return version if version.startswith("v") else f"v{version}"


class LiveWhatsAppGraph:
    live = True

    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None) -> None:
        self._base = settings.whatsapp_graph_base_url.rstrip("/")
        self._client = client or httpx.AsyncClient(timeout=settings.whatsapp_graph_timeout_s)
        self._owns_client = client is None

    async def _request(
        self, method: str, token: str, path: str, *, params: dict[str, str] | None = None, json: Any = None
    ) -> dict[str, Any]:
        try:
            response = await self._client.request(
                method,
                f"{self._base}/{path}",
                params=params,
                json=json,
                headers={"Authorization": f"Bearer {token}"},
            )
        except httpx.HTTPError as exc:
            raise GraphError("unreachable", "WhatsApp could not be reached. Try again in a minute.") from exc
        try:
            body = response.json()
        except ValueError:
            body = {}
        if response.status_code >= 500:
            raise GraphError(
                "unreachable", f"WhatsApp answered with an error ({response.status_code}). Try again later."
            )
        if response.status_code >= 400:
            error = body.get("error") if isinstance(body, dict) else None
            message = error.get("message") if isinstance(error, dict) else None
            raise GraphError(
                "rejected", str(message or f"WhatsApp refused the request ({response.status_code}).")
            )
        return body if isinstance(body, dict) else {}

    async def check_number(self, token: str, version: str, phone_number_id: str) -> NumberInfo:
        body = await self._request(
            "GET",
            token,
            f"{_version(version)}/{phone_number_id}",
            params={"fields": "display_phone_number,verified_name"},
        )
        return NumberInfo(body.get("display_phone_number"), body.get("verified_name"))

    async def enable_calling(self, token: str, version: str, phone_number_id: str, sip_host: str) -> None:
        host = sip_host.split(":")[0]
        await self._request(
            "POST",
            token,
            f"{_version(version)}/{phone_number_id}/settings",
            json={
                "calling": {
                    "status": "ENABLED",
                    "call_icon_visibility": "DEFAULT",
                    "sip": {"status": "ENABLED", "servers": [{"hostname": host, "port": SIP_PORT}]},
                }
            },
        )

    async def sip_credentials(
        self, token: str, version: str, phone_number_id: str, e164: str
    ) -> SipCredentials | None:
        body = await self._request(
            "GET",
            token,
            f"{_version(version)}/{phone_number_id}/settings",
            params={"include_sip_credentials": "true"},
        )
        servers = ((body.get("calling") or {}).get("sip") or {}).get("servers") or []
        for server in servers:
            password = server.get("sip_user_password") if isinstance(server, dict) else None
            if password:
                return SipCredentials(username=e164.lstrip("+"), password=str(password))
        return None

    async def disable_calling(self, token: str, version: str, phone_number_id: str) -> None:
        await self._request(
            "POST",
            token,
            f"{_version(version)}/{phone_number_id}/settings",
            json={"calling": {"status": "DISABLED"}},
        )

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()


@dataclass
class FakeWhatsAppGraph:
    """Local stand-in. A token containing ``invalid`` is rejected and one containing
    ``unreachable`` fails to connect; ``display_numbers`` maps ids to the number Meta would
    report (an id not in it reports no number, which skips the comparison)."""

    live: bool = False
    display_numbers: dict[str, str] = field(default_factory=dict)
    enabled: dict[str, str] = field(default_factory=dict)
    disabled: list[str] = field(default_factory=list)

    def _check(self, token: str) -> None:
        if "unreachable" in token:
            raise GraphError("unreachable", "WhatsApp could not be reached. Try again in a minute.")
        if "invalid" in token:
            raise GraphError("rejected", "Error validating access token: Session has expired.")

    async def check_number(self, token: str, version: str, phone_number_id: str) -> NumberInfo:
        self._check(token)
        return NumberInfo(self.display_numbers.get(phone_number_id), "Fake business")

    async def enable_calling(self, token: str, version: str, phone_number_id: str, sip_host: str) -> None:
        self._check(token)
        self.enabled[phone_number_id] = sip_host

    async def sip_credentials(
        self, token: str, version: str, phone_number_id: str, e164: str
    ) -> SipCredentials | None:
        self._check(token)
        return SipCredentials(username=e164.lstrip("+"), password=f"fake-sip-{phone_number_id[-6:]}")

    async def disable_calling(self, token: str, version: str, phone_number_id: str) -> None:
        self._check(token)
        self.enabled.pop(phone_number_id, None)
        self.disabled.append(phone_number_id)

    async def aclose(self) -> None:
        return None


def build_graph(settings: Settings) -> WhatsAppGraph:
    return LiveWhatsAppGraph(settings) if settings.whatsapp_graph_live else FakeWhatsAppGraph()
