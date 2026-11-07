"""X-Hub-Signature-256 checks and verify-token hashing (010 T046, research R11)."""

from __future__ import annotations

import hashlib
import hmac

from app.channels.whatsapp.signatures import sign, verify_signature, verify_token_hash

BODY = b'{"object":"whatsapp_business_account","entry":[]}'


def test_valid_signature() -> None:
    header = "sha256=" + hmac.new(b"app-secret", BODY, hashlib.sha256).hexdigest()
    assert verify_signature("app-secret", BODY, header)
    assert sign("app-secret", BODY) == header
    assert verify_signature("app-secret", BODY, header.upper().replace("SHA256=", "sha256="))


def test_tampered_body_and_wrong_secret() -> None:
    header = sign("app-secret", BODY)
    assert not verify_signature("app-secret", BODY + b" ", header)
    assert not verify_signature("other-secret", BODY, header)


def test_malformed_headers() -> None:
    for header in (None, "", "sha256=", "sha1=" + "0" * 40, "sha256=xyz", "sha256=" + "0" * 63, "0" * 64):
        assert not verify_signature("app-secret", BODY, header)


def test_verify_token_hash() -> None:
    assert verify_token_hash("verify-me-123") == hashlib.sha256(b"verify-me-123").hexdigest()
    assert verify_token_hash("a") != verify_token_hash("b")
