"""Payment provider adapter (T053): hosted checkout sessions and webhook signature checks.

* ``FakeStripeGateway`` (``STRIPE_MODE=fake``): no network. Checkout URLs point at the API's dev
  page ``/v1/dev/fake-checkout/{id}``, which signs a ``checkout.session.completed`` event with
  the configured webhook secret and feeds it through the same verification path as real
  webhooks.
* ``LiveStripeGateway`` (``STRIPE_MODE=live``): Stripe REST API over ``httpx`` (form encoded,
  ``Idempotency-Key`` forwarded).

Webhook signatures follow Stripe's scheme in both modes: header ``t=<unix>,v1=<hex>``, where
``v1 = HMAC-SHA256(secret, f"{t}.{payload}")``, with a timestamp tolerance (default 300 s).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, Protocol

import httpx
from ulid import ULID

from app.core.config import Settings

STRIPE_API = "https://api.stripe.com/v1"


class SignatureError(Exception):
    """The Stripe-Signature header is missing, malformed, stale or does not match."""


def compute_signature(payload: bytes, secret: str, timestamp: int) -> str:
    signed = f"{timestamp}.".encode() + payload
    return hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()


def sign_payload(payload: bytes, secret: str, timestamp: int | None = None) -> str:
    """Build a ``Stripe-Signature`` header value (fake mode and tests)."""
    ts = int(time.time()) if timestamp is None else timestamp
    return f"t={ts},v1={compute_signature(payload, secret, ts)}"


def verify_signature(
    payload: bytes, header: str | None, secret: str, *, tolerance_s: int = 300, now: int | None = None
) -> dict[str, Any]:
    """Verify the header and return the parsed event."""
    if not header:
        raise SignatureError("missing signature header")
    timestamp: int | None = None
    candidates: list[str] = []
    for part in header.split(","):
        key, _, value = part.strip().partition("=")
        if key == "t":
            try:
                timestamp = int(value)
            except ValueError as exc:
                raise SignatureError("bad timestamp") from exc
        elif key == "v1":
            candidates.append(value)
    if timestamp is None or not candidates:
        raise SignatureError("malformed signature header")
    expected = compute_signature(payload, secret, timestamp)
    if not any(hmac.compare_digest(expected, c) for c in candidates):
        raise SignatureError("signature mismatch")
    current = int(time.time()) if now is None else now
    if tolerance_s > 0 and abs(current - timestamp) > tolerance_s:
        raise SignatureError("timestamp outside tolerance")
    try:
        event = json.loads(payload)
    except ValueError as exc:
        raise SignatureError("payload is not JSON") from exc
    if not isinstance(event, dict):
        raise SignatureError("payload is not an object")
    return event


@dataclass(frozen=True)
class CreatedCheckout:
    id: str
    url: str
    expires_at: datetime


class StripeGateway(Protocol):
    mode: str

    async def create_checkout_session(
        self,
        *,
        amount_usd: Decimal,
        workspace_id: str,
        success_url: str,
        cancel_url: str,
        idempotency_key: str | None,
    ) -> CreatedCheckout: ...

    def verify_webhook(self, payload: bytes, header: str | None) -> dict[str, Any]: ...


class _Verifier:
    def __init__(self, settings: Settings) -> None:
        self._secret = settings.stripe_webhook_secret.get_secret_value()
        self._tolerance = settings.stripe_webhook_tolerance_s

    def verify_webhook(self, payload: bytes, header: str | None) -> dict[str, Any]:
        return verify_signature(payload, header, self._secret, tolerance_s=self._tolerance)

    def sign(self, payload: bytes) -> str:
        return sign_payload(payload, self._secret)


class FakeStripeGateway(_Verifier):
    mode = "fake"

    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)
        self._api_base = settings.api_base_url.rstrip("/")

    async def create_checkout_session(
        self,
        *,
        amount_usd: Decimal,
        workspace_id: str,
        success_url: str,
        cancel_url: str,
        idempotency_key: str | None,
    ) -> CreatedCheckout:
        session_id = f"cs_test_fake_{ULID()}"
        return CreatedCheckout(
            id=session_id,
            url=f"{self._api_base}/v1/dev/fake-checkout/{session_id}",
            expires_at=datetime.now(UTC) + timedelta(hours=24),
        )


class LiveStripeGateway(_Verifier):
    mode = "live"

    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None) -> None:
        super().__init__(settings)
        if settings.stripe_secret_key is None:
            raise ValueError("STRIPE_SECRET_KEY is required in live mode")
        self._key = settings.stripe_secret_key.get_secret_value()
        self._client = client or httpx.AsyncClient(base_url=STRIPE_API, timeout=15.0)

    async def create_checkout_session(
        self,
        *,
        amount_usd: Decimal,
        workspace_id: str,
        success_url: str,
        cancel_url: str,
        idempotency_key: str | None,
    ) -> CreatedCheckout:
        cents = int((amount_usd * 100).to_integral_value())
        form = {
            "mode": "payment",
            "success_url": success_url,
            "cancel_url": cancel_url,
            "client_reference_id": workspace_id,
            "metadata[workspace_id]": workspace_id,
            "payment_intent_data[metadata][workspace_id]": workspace_id,
            "line_items[0][quantity]": "1",
            "line_items[0][price_data][currency]": "usd",
            "line_items[0][price_data][unit_amount]": str(cents),
            "line_items[0][price_data][product_data][name]": "Callwright credit",
        }
        headers = {"Authorization": f"Bearer {self._key}"}
        if idempotency_key:
            headers["Idempotency-Key"] = f"checkout:{workspace_id}:{idempotency_key}"
        response = await self._client.post("/checkout/sessions", data=form, headers=headers)
        response.raise_for_status()
        body = response.json()
        return CreatedCheckout(
            id=str(body["id"]),
            url=str(body["url"]),
            expires_at=datetime.fromtimestamp(int(body["expires_at"]), UTC),
        )


def build_gateway(settings: Settings) -> FakeStripeGateway | LiveStripeGateway:
    if settings.stripe_mode == "live":
        return LiveStripeGateway(settings)
    return FakeStripeGateway(settings)
