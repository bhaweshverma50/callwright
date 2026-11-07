"""WhatsApp webhook checks (010 T051, research R11).

* ``X-Hub-Signature-256: sha256=<hex>`` is HMAC-SHA256 of the raw request body with the Meta
  app secret; compared in constant time.
* Verify tokens are looked up by their SHA-256 (an indexed column), so the token itself is only
  stored encrypted.
"""

from __future__ import annotations

import hashlib
import hmac
import re

_HEADER = re.compile(r"^sha256=([0-9a-f]{64})$")


def sign(app_secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(app_secret.encode(), body, hashlib.sha256).hexdigest()


def verify_signature(app_secret: str, body: bytes, header: str | None) -> bool:
    match = _HEADER.match((header or "").strip().lower())
    if match is None:
        return False
    expected = hmac.new(app_secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, match.group(1))


def verify_token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
