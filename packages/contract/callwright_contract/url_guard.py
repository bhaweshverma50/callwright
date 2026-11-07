"""SSRF guard for outbound HTTP to customer-supplied URLs (003 T089, research R15, FR-040).

``check_url`` parses the URL, refuses non-HTTPS outside development, resolves the host and
refuses it when *any* resolved address is private, loopback, link-local (which includes the
cloud metadata address 169.254.169.254), carrier-grade NAT, multicast, reserved or unspecified,
including IPv6 equivalents and IPv4-mapped IPv6 addresses.

Callers then connect to the address that was checked, not to a fresh DNS answer, so a host that
resolves to a public address at check time and a private one a moment later (DNS rebinding)
cannot redirect the request: ``pinned_url`` replaces the URL's host by the checked IP while
``host_header`` and the TLS server name (SNI and certificate check) keep the original name. Used
by the API (webhooks, inbound routing webhooks, HTTP tool test runs) and the worker (HTTP tools).
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address
Resolver = Callable[[str, int], Awaitable[list[str]]]

_EXTRA_BLOCKED = tuple(
    ipaddress.ip_network(n)
    for n in (
        "0.0.0.0/8",  # "this network"
        "100.64.0.0/10",  # carrier-grade NAT (also Alibaba metadata 100.100.100.200)
        "192.0.0.0/24",  # IETF protocol assignments
        "198.18.0.0/15",  # benchmarking
        "64:ff9b::/96",  # NAT64 (embeds IPv4)
        "64:ff9b:1::/48",
        "2002::/16",  # 6to4 (embeds IPv4)
        "fc00::/7",  # unique local (includes fd00:ec2::254, AWS metadata over IPv6)
    )
)


class UrlNotAllowed(Exception):
    """The URL may not be called; ``reason`` is a short machine-readable code."""

    def __init__(self, reason: str, detail: str) -> None:
        super().__init__(detail)
        self.reason = reason
        self.detail = detail


@dataclass(frozen=True)
class CheckedUrl:
    url: str
    scheme: str
    host: str
    port: int
    addresses: tuple[str, ...]


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
    loop = asyncio.get_running_loop()
    infos = await loop.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return [str(info[4][0]) for info in infos]


def _strip_scope(address: str) -> str:
    return address.split("%", 1)[0]


async def check_url(
    url: str,
    *,
    allow_http: bool = False,
    allow_private: bool = False,
    resolver: Resolver | None = None,
) -> CheckedUrl:
    """Validate ``url`` and resolve it to addresses that may be called."""
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError as exc:
        raise UrlNotAllowed("invalid_url", "The URL is not valid.") from exc
    scheme = parts.scheme.lower()
    if scheme not in ("https", "http"):
        raise UrlNotAllowed("invalid_url", "Only http and https URLs are supported.")
    if scheme == "http" and not allow_http:
        raise UrlNotAllowed("https_required", "Webhook URLs must use https.")
    host = (parts.hostname or "").rstrip(".").lower()
    if not host:
        raise UrlNotAllowed("invalid_url", "The URL has no host.")
    if parts.username or parts.password:
        raise UrlNotAllowed("invalid_url", "Credentials in the URL are not allowed.")
    port = port or (443 if scheme == "https" else 80)
    try:
        literal: IPAddress | None = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None:
        addresses = [str(literal)]
    else:
        private_name = host == "localhost" or host.endswith((".localhost", ".internal"))
        if private_name and not allow_private:
            raise UrlNotAllowed("private_address", f"{host} is a private host name.")
        try:
            addresses = [_strip_scope(a) for a in await (resolver or system_resolver)(host, port)]
        except (OSError, UnicodeError) as exc:
            raise UrlNotAllowed("dns_failure", f"Could not resolve {host}.") from exc
        if not addresses:
            raise UrlNotAllowed("dns_failure", f"Could not resolve {host}.")
    if not allow_private:
        blocked = [a for a in addresses if is_blocked_ip(a)]
        if blocked:
            raise UrlNotAllowed(
                "private_address",
                f"{host} resolves to a private or reserved address ({blocked[0]}).",
            )
    return CheckedUrl(url=url, scheme=scheme, host=host, port=port, addresses=tuple(dict.fromkeys(addresses)))


def pinned_url(checked: CheckedUrl, address: str) -> str:
    parts = urlsplit(checked.url)
    ip = ipaddress.ip_address(address)
    host = f"[{ip}]" if ip.version == 6 else str(ip)
    default = 443 if checked.scheme == "https" else 80
    netloc = host if checked.port == default else f"{host}:{checked.port}"
    return urlunsplit((checked.scheme, netloc, parts.path or "/", parts.query, ""))


def host_header(checked: CheckedUrl) -> str:
    default = 443 if checked.scheme == "https" else 80
    host = f"[{checked.host}]" if ":" in checked.host else checked.host
    return host if checked.port == default else f"{host}:{checked.port}"


def blocked_networks() -> Iterable[ipaddress.IPv4Network | ipaddress.IPv6Network]:
    return _EXTRA_BLOCKED
