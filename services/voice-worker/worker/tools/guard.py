"""Address guard for HTTP tools on calls (research R4): the worker's copy of the API's
``core/url_guard``. The host is resolved once, every answer must be public, and the request goes
to the vetted IP with the original Host header and TLS server name (no DNS rebinding)."""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

Resolver = Callable[[str, int], Awaitable[list[str]]]
IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address

_EXTRA_BLOCKED = tuple(
    ipaddress.ip_network(n)
    for n in (
        "0.0.0.0/8",
        "100.64.0.0/10",
        "192.0.0.0/24",
        "198.18.0.0/15",
        "64:ff9b::/96",
        "64:ff9b:1::/48",
        "2002::/16",
        "fc00::/7",
    )
)


class Blocked(Exception):
    def __init__(self, reason: str, detail: str) -> None:
        super().__init__(detail)
        self.reason = reason
        self.detail = detail


@dataclass(frozen=True)
class Target:
    url: str
    scheme: str
    host: str
    port: int
    address: str

    def pinned_url(self) -> str:
        parts = urlsplit(self.url)
        ip = ipaddress.ip_address(self.address)
        host = f"[{ip}]" if ip.version == 6 else str(ip)
        default = 443 if self.scheme == "https" else 80
        netloc = host if self.port == default else f"{host}:{self.port}"
        return urlunsplit((self.scheme, netloc, parts.path or "/", parts.query, ""))

    def host_header(self) -> str:
        default = 443 if self.scheme == "https" else 80
        host = f"[{self.host}]" if ":" in self.host else self.host
        return host if self.port == default else f"{host}:{self.port}"


def is_blocked_ip(value: str | IPAddress) -> bool:
    ip = ipaddress.ip_address(value) if isinstance(value, str) else value
    if isinstance(ip, ipaddress.IPv6Address):
        mapped = ip.ipv4_mapped or ip.sixtofour
        if mapped is not None and is_blocked_ip(mapped):
            return True
        if ip.teredo is not None:
            return True
    if (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    ):
        return True
    return any(ip.version == net.version and ip in net for net in _EXTRA_BLOCKED)


async def system_resolver(host: str, port: int) -> list[str]:
    infos = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return [str(info[4][0]).split("%", 1)[0] for info in infos]


async def check(url: str, *, allow_http: bool = False, resolver: Resolver | None = None) -> Target:
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError as exc:
        raise Blocked("invalid_url", "The URL is not valid.") from exc
    scheme = parts.scheme.lower()
    if scheme not in ("http", "https"):
        raise Blocked("invalid_url", "Only http and https URLs are supported.")
    if scheme == "http" and not allow_http:
        raise Blocked("https_required", "The URL must use https.")
    host = (parts.hostname or "").rstrip(".").lower()
    if not host or parts.username or parts.password:
        raise Blocked("invalid_url", "The URL has no valid host.")
    port = port or (443 if scheme == "https" else 80)
    try:
        addresses = [str(ipaddress.ip_address(host))]
    except ValueError:
        if host == "localhost" or host.endswith((".localhost", ".internal")):
            raise Blocked("private_address", f"{host} is a private host name.") from None
        try:
            addresses = await (resolver or system_resolver)(host, port)
        except (OSError, UnicodeError) as exc:
            raise Blocked("dns_failure", f"Could not resolve {host}.") from exc
    if not addresses:
        raise Blocked("dns_failure", f"Could not resolve {host}.")
    if any(is_blocked_ip(a) for a in addresses):
        raise Blocked("private_address", f"{host} resolves to a private or reserved address.")
    return Target(url=url, scheme=scheme, host=host, port=port, address=addresses[0])
