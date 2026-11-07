"""Webhook signatures (003 T085, FR-037): fixed vector, dual signature in rotation, and the
receiver check from quickstart.md section 7."""

from __future__ import annotations

import hashlib
import hmac
import re

from app.webhooks_out import signing
from app.webhooks_out.service import new_secret

BODY = b'{"event":"ping","event_id":"evt_1"}'
SECRET = "whsec_test_secret_0123456789"
T = 1_760_600_000


def _receiver_accepts(header: str, secret: str, body: bytes = BODY) -> bool:
    """The receiver snippet from quickstart.md section 7."""
    parts = [p.split("=", 1) for p in header.split(",")]
    t = int(next(v for k, v in parts if k == "t"))
    computed = hmac.new(secret.encode(), f"{t}.".encode() + body, hashlib.sha256).hexdigest()
    return any(hmac.compare_digest(computed, v) for k, v in parts if k == "v1")


def test_fixed_vector() -> None:
    expected = hmac.new(b"whsec_test_secret_0123456789", b"1760600000." + BODY, "sha256").hexdigest()
    assert signing.sign(BODY, [SECRET], T) == f"t={T},v1={expected}"


def test_receiver_accepts_the_signed_body_only() -> None:
    header = signing.sign(BODY, [SECRET], T)
    assert _receiver_accepts(header, SECRET)
    assert not _receiver_accepts(header, SECRET, BODY + b" ")


def test_dual_signature_during_rotation() -> None:
    new, old = "whsec_new_secret_aaaaaaaa", "whsec_old_secret_bbbbbbbb"
    header = signing.sign(BODY, [new, old], T)
    assert header.count("v1=") == 2
    assert _receiver_accepts(header, new) and _receiver_accepts(header, old)
    assert not _receiver_accepts(header, "whsec_someone_else_cccccc")


def test_secret_format() -> None:
    secret = new_secret()
    assert re.fullmatch(r"whsec_[A-Za-z0-9_-]{43}", secret)
    assert new_secret() != secret
