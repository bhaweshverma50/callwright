"""Webhook signatures (003 T085, FR-037): fixed vector, dual signature in rotation, tolerance."""

from __future__ import annotations

import hashlib
import hmac

import pytest

from app.webhooks_out import signing
from app.webhooks_out.service import new_secret

BODY = b'{"event":"ping","event_id":"evt_1"}'
SECRET = "whsec_test_secret_0123456789"
T = 1_760_600_000


def test_fixed_vector() -> None:
    expected = hmac.new(SECRET.encode(), f"{T}.".encode() + BODY, hashlib.sha256).hexdigest()
    assert signing.compute(SECRET, T, BODY) == expected
    assert signing.sign(BODY, [SECRET], T) == f"t={T},v1={expected}"
    # Known answer, so a change to the scheme cannot slip through.
    assert expected == hmac.new(b"whsec_test_secret_0123456789", b"1760600000." + BODY, "sha256").hexdigest()


def test_verify_round_trip_and_quickstart_receiver() -> None:
    header = signing.sign(BODY, [SECRET], T)
    assert signing.verify(BODY, header, SECRET, now=T + 10) == T
    # The receiver snippet from quickstart.md section 7.
    parts = [p.split("=", 1) for p in header.split(",")]
    t = int(next(v for k, v in parts if k == "t"))
    computed = hmac.new(SECRET.encode(), f"{t}.".encode() + BODY, hashlib.sha256).hexdigest()
    assert any(hmac.compare_digest(computed, v) for k, v in parts if k == "v1")


def test_dual_signature_during_rotation() -> None:
    new, old = "whsec_new_secret_aaaaaaaa", "whsec_old_secret_bbbbbbbb"
    header = signing.sign(BODY, [new, old], T)
    assert header.count("v1=") == 2
    assert signing.verify(BODY, header, new, now=T) == T
    assert signing.verify(BODY, header, old, now=T) == T
    with pytest.raises(signing.SignatureError):
        signing.verify(BODY, header, "whsec_someone_else_cccccc", now=T)


@pytest.mark.parametrize("offset", [301, -301])
def test_outside_300_seconds_is_rejected(offset: int) -> None:
    header = signing.sign(BODY, [SECRET], T)
    with pytest.raises(signing.SignatureError, match="tolerance"):
        signing.verify(BODY, header, SECRET, now=T + offset)
    assert signing.verify(BODY, header, SECRET, now=T + 300) == T


def test_tampered_body_and_bad_headers() -> None:
    header = signing.sign(BODY, [SECRET], T)
    with pytest.raises(signing.SignatureError):
        signing.verify(BODY + b" ", header, SECRET, now=T)
    for bad in (None, "", "v1=abc", "t=notanumber,v1=abc", f"t={T}"):
        with pytest.raises(signing.SignatureError):
            signing.verify(BODY, bad, SECRET, now=T)


def test_secret_format() -> None:
    import re

    secret = new_secret()
    assert re.fullmatch(r"whsec_[A-Za-z0-9_-]{43}", secret)
    assert new_secret() != secret
