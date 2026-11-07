"""Customer webhook signatures (003 T088, research R15, FR-037).

Header ``Callwright-Signature: t=<unix seconds>,v1=<hex>[,v1=<hex>]`` where each ``v1`` is
HMAC-SHA256 over ``"{t}.{raw body}"`` with one workspace secret. During the 24-hour rotation
overlap the delivery carries a signature for the new and the previous secret, so receivers that
still hold the old secret keep verifying. Receivers reject a ``t`` more than 300 s from their clock.
"""

from __future__ import annotations

import hashlib
import hmac
import time
from collections.abc import Sequence

HEADER = "Callwright-Signature"


def compute(secret: str, timestamp: int, body: bytes) -> str:
    return hmac.new(secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256).hexdigest()


def sign(body: bytes, secrets: Sequence[str], timestamp: int | None = None) -> str:
    """Header value signing ``body`` with every secret (current first)."""
    if not secrets:
        raise ValueError("at least one secret is required")
    t = int(time.time()) if timestamp is None else timestamp
    return ",".join([f"t={t}", *(f"v1={compute(s, t, body)}" for s in secrets)])
