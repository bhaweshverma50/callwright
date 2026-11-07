"""Webhook address rules (T014, FR-013, research R20).

``check_syntax`` is pure: an absolute ``https://`` URL (``http://`` only in development) of at
most 2,048 characters whose host is not an IP literal or well-known name in a private, loopback,
link-local or metadata range. ``check_resolved`` resolves the host and applies the same range
rules to every address; a host that does not resolve is accepted here because 003 re-checks the
address at send time. ``WEBHOOKS_ALLOW_PRIVATE`` (development only; production refuses it) lifts
the range rules, as it does for 003's delivery, so a local receiver can be set on an agent.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from urllib.parse import urlsplit

from callwright_contract import url_guard

MAX_LENGTH = 2048
BLOCKED_HOSTNAMES = frozenset({"localhost", "metadata", "metadata.google.internal", "instance-data"})
BLOCKED_SUFFIXES = (".localhost", ".local", ".internal", ".localdomain", ".home.arpa")
Resolver = Callable[[str], Awaitable[list[str]]]


def _private_allowed() -> bool:
    from app.core.config import get_settings

    return get_settings().webhooks_allow_private


@dataclass(frozen=True)
class UrlIssue:
    code: str
    message: str


def is_blocked_ip(value: str) -> bool:
    """The outbound URL guard's ranges, for an address literal (``[v6]`` and zone ids allowed)."""
    try:
        return url_guard.is_blocked_ip(value.strip("[]").split("%")[0])
    except ValueError:
        return False


def _is_ip_literal(host: str) -> bool:
    try:
        ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        return False
    return True


def check_syntax(url: str, *, allow_http: bool = False, allow_private: bool | None = None) -> UrlIssue | None:
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
    if _private_allowed() if allow_private is None else allow_private:
        return None
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


async def check_resolved(
    url: str, resolver: Resolver | None = None, *, allow_private: bool | None = None
) -> UrlIssue | None:
    """Resolve the host and refuse any private, loopback, link-local or metadata address."""
    if _private_allowed() if allow_private is None else allow_private:
        return None
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
