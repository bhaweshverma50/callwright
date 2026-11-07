"""E.164, termination address and CIDR rules (010 T006, research R12, R14)."""

from __future__ import annotations

import pytest

from app.channels.validation import (
    InvalidValue,
    normalize_number,
    normalize_whatsapp_caller,
    parse_cidrs,
    parse_e164,
    parse_termination,
)


@pytest.mark.parametrize("value", ["+14155550100", "+919876543210", "+442071838750"])
def test_e164_accepts(value: str) -> None:
    assert parse_e164(value) == value


@pytest.mark.parametrize(
    "value", ["14155550100", "+1 415 555 0100", "+0123456789", "+1415", "", "+1415555010012345", "abc"]
)
def test_e164_rejects(value: str) -> None:
    with pytest.raises(InvalidValue):
        parse_e164(value)


def test_normalize_national_with_region() -> None:
    assert normalize_number("(415) 555-0199", "US") == "+14155550199"
    assert normalize_number("+1 415 555 0199") == "+14155550199"
    assert normalize_number("09876543210", "IN") == "+919876543210"
    with pytest.raises(InvalidValue):
        normalize_number("(415) 555-0199")  # no country code and no region
    with pytest.raises(InvalidValue):
        normalize_number("not a number", "US")


def test_whatsapp_caller_gets_plus() -> None:
    assert normalize_whatsapp_caller("14155550100") == "+14155550100"
    assert normalize_whatsapp_caller("+14155550100") == "+14155550100"
    with pytest.raises(InvalidValue):
        normalize_whatsapp_caller("12")


@pytest.mark.parametrize(
    ("raw", "host", "port", "transport"),
    [
        ("trunk.example-carrier.com:5060", "trunk.example-carrier.com", 5060, "auto"),
        ("sip:trunk.example-carrier.com:5060", "trunk.example-carrier.com", 5060, "auto"),
        ("SIP:Trunk.Example.com", "trunk.example.com", None, "auto"),
        ("sips:trunk.example.com", "trunk.example.com", None, "tls"),
        ("203.0.113.10", "203.0.113.10", None, "auto"),
        ("203.0.113.10:5080", "203.0.113.10", 5080, "auto"),
        ("[2001:db8::10]:5061", "[2001:db8::10]", 5061, "auto"),
        ("[2001:db8::10]", "[2001:db8::10]", None, "auto"),
    ],
)
def test_termination_accepts(raw: str, host: str, port: int | None, transport: str) -> None:
    assert parse_termination(raw, "auto") == (host, port, transport)


def test_sips_keeps_explicit_transport() -> None:
    assert parse_termination("sips:trunk.example.com", "tcp") == ("trunk.example.com", None, "tcp")


@pytest.mark.parametrize(
    "raw",
    [
        "user@trunk.example.com",
        "sip:+14155550100@trunk.example.com",
        "trunk.example.com/path",
        "trunk.example.com;transport=tcp",
        "trunk.example.com?x=1",
        "trunk.example.com:0",
        "trunk.example.com:70000",
        "trunk.example.com:abc",
        "2001:db8::10",
        "[not-an-ip]",
        "-bad-.example.com",
        "a" * 64 + ".example.com",
        "",
        "sip:",
        "trunk..example.com",
    ],
)
def test_termination_rejects(raw: str) -> None:
    with pytest.raises(InvalidValue):
        parse_termination(raw, "auto")


def test_cidrs() -> None:
    assert parse_cidrs(["203.0.113.0/24", "2001:db8::/32", "198.51.100.7"]) == [
        "203.0.113.0/24",
        "2001:db8::/32",
        "198.51.100.7/32",
    ]
    with pytest.raises(InvalidValue):
        parse_cidrs(["203.0.113.5/24"])  # host bits set
    with pytest.raises(InvalidValue):
        parse_cidrs(["nonsense"])
    with pytest.raises(InvalidValue):
        parse_cidrs([f"10.0.{i}.0/24" for i in range(21)])
