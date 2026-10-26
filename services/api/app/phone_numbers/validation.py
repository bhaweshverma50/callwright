"""Number and address rules shared by phone numbers, outbound and WhatsApp (010 T007, R12, R14).

* ``parse_e164``: strict E.164 (``+`` and 7 to 15 digits) that ``phonenumbers`` can place in a
  country. ``normalize_number`` also accepts national formats with a default region.
* ``parse_termination``: ``host[:port]`` where host is a DNS name, IPv4 or bracketed IPv6. A
  leading ``sip:``/``sips:`` is removed (``sips:`` means TLS when the transport is ``auto``);
  anything with a user part, path, parameters or query is refused.
* ``parse_cidrs``: up to 20 IPv4 or IPv6 networks; a bare address becomes a /32 or /128.
"""

from __future__ import annotations

import ipaddress
import re
from collections.abc import Sequence

import phonenumbers

E164 = re.compile(r"^\+[1-9]\d{6,14}$")
MAX_CIDRS = 20
_LABEL = re.compile(r"^(?!-)[a-z0-9-]{1,63}(?<!-)$")


class InvalidValue(ValueError):
    """A value that breaks a channel rule; the message is safe to show."""


def _possible(parsed: phonenumbers.PhoneNumber) -> bool:
    return bool(phonenumbers.is_possible_number(parsed)) and (
        phonenumbers.region_code_for_number(parsed) is not None
    )


def parse_e164(value: str) -> str:
    if not isinstance(value, str) or not E164.match(value):
        raise InvalidValue("Enter the number in E.164 form, for example +14155550123.")
    try:
        parsed = phonenumbers.parse(value, None)
    except phonenumbers.NumberParseException as exc:
        raise InvalidValue("Enter the number in E.164 form, for example +14155550123.") from exc
    if not _possible(parsed):
        raise InvalidValue("This is not a possible phone number for its country.")
    return value


def normalize_number(value: str, default_region: str | None = None) -> str:
    """E.164 form of ``value``; national formats need ``default_region`` (ISO 3166-1 alpha-2)."""
    raw = (value or "").strip()
    if not raw:
        raise InvalidValue("Enter a phone number.")
    try:
        parsed = phonenumbers.parse(raw, default_region.upper() if default_region else None)
    except phonenumbers.NumberParseException as exc:
        if not raw.startswith("+") and not default_region:
            raise InvalidValue("Add the country code, or choose a default region.") from exc
        raise InvalidValue("This is not a phone number.") from exc
    if not _possible(parsed):
        raise InvalidValue("This is not a possible phone number for its country.")
    e164 = phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
    if not E164.match(e164):
        raise InvalidValue("This is not a phone number.")
    return e164


def normalize_whatsapp_caller(value: str) -> str:
    """WhatsApp sends caller ids as digits without ``+`` (research R12)."""
    raw = (value or "").strip().replace(" ", "")
    if raw and not raw.startswith("+"):
        raw = "+" + raw
    return parse_e164(raw)


def _host(raw: str) -> str:
    if raw.startswith("["):
        if not raw.endswith("]"):
            raise InvalidValue("A bracketed IPv6 address must end with ']'.")
        try:
            ip = ipaddress.IPv6Address(raw[1:-1])
        except ValueError as exc:
            raise InvalidValue("The address in brackets is not a valid IPv6 address.") from exc
        return f"[{ip.compressed}]"
    try:
        return str(ipaddress.IPv4Address(raw))
    except ValueError:
        pass
    if ":" in raw:
        raise InvalidValue("Put IPv6 addresses in brackets, for example [2001:db8::10]:5060.")
    try:
        host = raw.encode("idna").decode("ascii").lower().rstrip(".")
    except UnicodeError as exc:
        raise InvalidValue("The host name is not valid.") from exc
    if not host or len(host) > 253 or not all(_LABEL.match(label) for label in host.split(".")):
        raise InvalidValue("Enter a host name, an IPv4 address or a bracketed IPv6 address.")
    return host


def parse_termination(value: str, transport: str = "auto") -> tuple[str, int | None, str]:
    """``(host, port, transport)`` for a termination address."""
    raw = (value or "").strip()
    lowered = raw.lower()
    if lowered.startswith("sips:"):
        raw = raw[5:]
        if transport == "auto":
            transport = "tls"
    elif lowered.startswith("sip:"):
        raw = raw[4:]
    if not raw:
        raise InvalidValue("Enter the carrier's termination address, for example trunk.example.com:5060.")
    if any(ch in raw for ch in "@;/?"):
        raise InvalidValue("Enter only a host and optional port: no user part, path or parameters.")
    host_part, port = raw, None
    if raw.startswith("["):
        end = raw.find("]")
        if end == -1:
            raise InvalidValue("A bracketed IPv6 address must end with ']'.")
        host_part, rest = raw[: end + 1], raw[end + 1 :]
        if rest:
            if not rest.startswith(":"):
                raise InvalidValue("Enter only a host and optional port.")
            port = _port(rest[1:])
    elif raw.count(":") == 1:
        host_part, port_text = raw.split(":")
        port = _port(port_text)
    return _host(host_part), port, transport


def _port(text: str) -> int:
    if not text.isdigit() or not 1 <= int(text) <= 65535:
        raise InvalidValue("The port must be a number from 1 to 65535.")
    return int(text)


def parse_cidrs(values: Sequence[str]) -> list[str]:
    if len(values) > MAX_CIDRS:
        raise InvalidValue(f"At most {MAX_CIDRS} address ranges are allowed.")
    out: list[str] = []
    for value in values:
        try:
            network = ipaddress.ip_network(value.strip(), strict=True)
        except ValueError as exc:
            raise InvalidValue(
                f"{value!r} is not a valid IPv4 or IPv6 range (for example 203.0.113.0/24)."
            ) from exc
        text = str(network)
        if text not in out:
            out.append(text)
    return out
