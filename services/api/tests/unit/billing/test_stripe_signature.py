"""Stripe webhook signature scheme (T053): our verifier agrees with the Stripe SDK."""

from __future__ import annotations

import json
import time

import pytest
import stripe

from app.billing.stripe_gateway import SignatureError, sign_payload, verify_signature

SECRET = "whsec_test_secret_for_unit_tests"
PAYLOAD = json.dumps({"id": "evt_1", "type": "checkout.session.completed"}).encode()


def test_round_trip() -> None:
    header = sign_payload(PAYLOAD, SECRET)
    assert verify_signature(PAYLOAD, header, SECRET)["id"] == "evt_1"


def test_stripe_sdk_accepts_our_signature() -> None:
    header = sign_payload(PAYLOAD, SECRET)
    assert stripe.WebhookSignature.verify_header(PAYLOAD.decode(), header, SECRET, tolerance=300)


def test_we_accept_a_signature_built_like_stripes() -> None:
    ts = int(time.time())
    expected = stripe.WebhookSignature._compute_signature(f"{ts}.{PAYLOAD.decode()}", SECRET)
    header = f"t={ts},v1=deadbeef,v1={expected},v0=ignored"
    assert verify_signature(PAYLOAD, header, SECRET)["type"] == "checkout.session.completed"


@pytest.mark.parametrize(
    "header",
    [None, "", "garbage", "t=abc,v1=00", "v1=00", f"t={int(time.time())}"],
)
def test_malformed_headers_rejected(header: str | None) -> None:
    with pytest.raises(SignatureError):
        verify_signature(PAYLOAD, header, SECRET)


def test_wrong_secret_rejected() -> None:
    with pytest.raises(SignatureError, match="mismatch"):
        verify_signature(PAYLOAD, sign_payload(PAYLOAD, "whsec_other"), SECRET)


def test_tampered_payload_rejected() -> None:
    header = sign_payload(PAYLOAD, SECRET)
    with pytest.raises(SignatureError):
        verify_signature(PAYLOAD + b" ", header, SECRET)


def test_stale_timestamp_rejected() -> None:
    old = int(time.time()) - 3600
    with pytest.raises(SignatureError, match="tolerance"):
        verify_signature(PAYLOAD, sign_payload(PAYLOAD, SECRET, old), SECRET, tolerance_s=300)
