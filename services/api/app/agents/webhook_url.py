"""Webhook address rules (T014, FR-013, research R20).

``check_syntax`` is pure: an absolute ``https://`` URL (``http://`` only in development) of at
most 2,048 characters whose host is not an IP literal or well-known name in a private, loopback,
link-local or metadata range. ``check_resolved`` resolves the host and applies the same range
rules to every address; a host that does not resolve is accepted here because 003 re-checks the
address at send time.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from urllib.parse import urlsplit

MAX_LENGTH = 2048
BLOCKED_HOSTNAMES = frozenset({"localhost", "metadata", "metadata.google.internal", "instance-data"})
BLOCKED_SUFFIXES = (".localhost", ".local", ".internal", ".localdomain", ".home.arpa")
_EXTRA_BLOCKED_NETS = (
    ipaddress.ip_network("100.64.0.0/10"),  # carrier-grade NAT
    ipaddress.ip_network("169.254.0.0/16"),  # link-local and cloud metadata
    ipaddress.ip_network("fd00:ec2::/32"),  # AWS IMDS over IPv6
)

Resolver = Callable[[str], Awaitable[list[str]]]


@dataclass(frozen=True)
class UrlIssue:
    code: str
    message: str


def is_blocked_ip(value: str) -> bool:
    try:
        ip = ipaddress.ip_address(value.strip("[]").split("%")[0])
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    if any(ip in net for net in _EXTRA_BLOCKED_NETS):
        return True
    return bool(
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
        or not ip.is_global
    )


def _is_ip_literal(host: str) -> bool:
    try:
        ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        return False
    return True


def check_syntax(url: str, *, allow_http: bool = False) -> UrlIssue | None:
    if len(url) > MAX_LENGTH:
        return UrlIssue("out_of_range", f"The webhook address can be at most {MAX_LENGTH} characters.")
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return UrlIssue("invalid_format", "Enter a full web address that starts with https://.")
    schemes = {"https", "http"} if allow_http else {"https"}
    if parts.scheme.lower() not in schemes or not parts.hostname:
        return UrlIssue("invalid_format", "Enter a full web address that starts with https://.")
    if parts.username or parts.password:
        return UrlIssue("invalid_format", "The webhook address cannot contain a user name or password.")
    try:
        _ = parts.port
    except ValueError:
        return UrlIssue("invalid_format", "The port in the webhook address is not valid.")
    host = parts.hostname.lower().rstrip(".")
    if host in BLOCKED_HOSTNAMES or host.endswith(BLOCKED_SUFFIXES):
        return UrlIssue("private_address", "The webhook address must point to a public host.")
    if _is_ip_literal(host):
        if is_blocked_ip(host):
            return UrlIssue("private_address", "The webhook address must point to a public host.")
    elif "." not in host:
        return UrlIssue("private_address", "The webhook address must point to a public host.")
    return None


async def default_resolver(host: str) -> list[str]:
    loop = asyncio.get_running_loop()
    infos = await asyncio.wait_for(loop.getaddrinfo(host, None, type=socket.SOCK_STREAM), timeout=2.0)
    return sorted({str(info[4][0]) for info in infos})


async def check_resolved(url: str, resolver: Resolver | None = None) -> UrlIssue | None:
    """Resolve the host and refuse any private, loopback, link-local or metadata address."""
    host = (urlsplit(url.strip()).hostname or "").lower()
    if not host or _is_ip_literal(host):
        return None
    try:
        addresses = await (resolver or default_resolver)(host)
    except (OSError, TimeoutError, UnicodeError):
        return None
    if any(is_blocked_ip(address) for address in addresses):
        return UrlIssue("private_address", "The webhook address must point to a public host.")
    return None
